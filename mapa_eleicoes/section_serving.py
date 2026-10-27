"""Resultantes por secao eleitoral, sem destruir a granularidade do TSE.

Converte votacao_secao_2026_UF.zip para Parquet por fonte/UF. Sao dados
individuais por NR_SECAO e cargo/turno, nunca geometrias inventadas.
As etapas parciais sao Parquets em disco; aggregacao final via Polars
streaming. Nao faz Pandas nem supoe coordenadas de uma secao.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import shutil
import zipfile
from pathlib import Path

import polars as pl

from mapa_eleicoes import cli

REVISION = 1
COLS = [
    "ano", "turno", "uf", "cd_municipio_tse", "municipio", "zona",
    "secao", "cargo", "numero", "candidato", "tipo_voto", "votos",
]
KEYS = COLS[:-1]
TEXT = ("uf", "cd_municipio_tse", "municipio", "cargo", "numero", "candidato", "tipo_voto")


def _section_batch(frame: pl.DataFrame, present: set[str], year: int, source_uf: str) -> pl.DataFrame:
    number = cli.first_key(present, "NR_VOTAVEL", "NR_CANDIDATO")
    candidate = cli.first_key(present, "NM_VOTAVEL", "NM_URNA_CANDIDATO")
    cargo = cli.first_key(present, "DS_CARGO", "DS_CARGO_PERGUNTA")
    if "ANO_ELEICAO" in present:
        frame = frame.filter(pl.col("ANO_ELEICAO") == str(year))
    if frame.is_empty():
        return pl.DataFrame()
    code = pl.col("CD_MUNICIPIO").str.strip_chars().str.strip_chars_start("0")
    df = frame.with_columns(
        pl.lit(year).cast(pl.Int32).alias("ano"),
        pl.col("NR_TURNO").cast(pl.Int16, strict=True).alias("turno"),
        (pl.col("SG_UF").str.strip_chars().str.to_uppercase()
         if "SG_UF" in present else pl.lit(source_uf)).alias("uf"),
        pl.when(code == "").then(pl.lit("0")).otherwise(code).alias("cd_municipio_tse"),
        pl.col("NM_MUNICIPIO").str.strip_chars().alias("municipio"),
        pl.col("NR_ZONA").cast(pl.Int32, strict=True).alias("zona"),
        pl.col("NR_SECAO").cast(pl.Int32, strict=True).alias("secao"),
        pl.col(cargo).str.strip_chars().alias("cargo"),
        pl.col(number).str.strip_chars().alias("numero"),
        pl.col(candidate).str.strip_chars().alias("candidato"),
        cli.classify_expr(present, number),
        pl.col("QT_VOTOS").cast(pl.Int64, strict=True).alias("votos"),
    ).select(COLS)
    if (df["votos"] < 0).any():
        raise ValueError("Resultado por secao com votos negativos")
    return df.group_by(KEYS).agg(pl.col("votos").sum())


def ingest_archive(
    source: Path, year: int, target: Path,
    chunksize: int = 100_000,
) -> dict:
    required = cli.REQUIRED | {"NR_SECAO"}
    names = cli.ensure_archive(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.parent / (target.name + ".shards")
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    rows = 0
    pieces = 0
    try:
        with zipfile.ZipFile(source) as archive:
            for name in names:
                with archive.open(name) as binary, io.TextIOWrapper(
                    binary, encoding="latin-1", newline=""
                ) as stream:
                    reader = csv.DictReader(stream, delimiter=";")
                    selected = [key for key in (reader.fieldnames or [])
                                if key.strip().upper() in cli.INPUT_COLUMNS]
                    present = {key.strip().upper() for key in selected}
                    if not required.issubset(present):
                        raise ValueError(
                            f"{name}: campos de secao ausentes: {sorted(required - present)}"
                        )
                    for frame in cli.iter_polars_batches(reader, selected, chunksize):
                        result = _section_batch(frame, present, year, source.stem[-2:].upper())
                        if result.is_empty():
                            continue
                        rows += frame.height
                        result.write_parquet(
                            stage / f"part_{pieces:08d}.parquet", compression="zstd"
                        )
                        pieces += 1
        if pieces == 0:
            raise ValueError(f"{source.name}: nenhum registro valido para {year}")
        # O sink streaming agrega shards em disco; sem carregar toda UF num
        # unico Python Counter/DataFrame de centenas de milhoes de linhas.
        partials = sorted(stage.glob("part_*.parquet"))
        scan = pl.scan_parquet([str(item) for item in partials])
        grouped = scan.group_by(KEYS).agg(pl.col("votos").sum()).select(COLS)
        pending = target.with_suffix(".part.parquet")
        try:
            grouped.sink_parquet(pending, compression="zstd")
            os.replace(pending, target)
        finally:
            pending.unlink(missing_ok=True)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return {
        "arquivo": source.name, "linhas_origem": rows, "partes": pieces,
        "parquet": target.name, "revisao": REVISION,
    }


def prepare_sections(year: int, root: Path | None = None) -> dict:
    data = root or cli.DATA
    raw = data / "raw" / str(year)
    out = data / "serving" / str(year) / "secoes"
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "catalog.json"
    previous = {}
    if manifest_path.is_file():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
    previous_files = previous.get("fontes", {}) if previous.get("revisao") == REVISION else {}
    files = sorted(raw.glob(f"votacao_secao_{year}_*.zip"))
    if not files:
        raise FileNotFoundError(f"Nenhum ZIP votacao_secao encontrado em {raw}")
    results = {}
    for source in files:
        uf = source.stem[-2:].upper()
        target = out / f"secoes_{uf}.parquet"
        st = source.stat()
        fingerprint = {"bytes": st.st_size, "mtime_ns": st.st_mtime_ns}
        old = previous_files.get(source.name, {})
        if target.exists() and old.get("fingerprint") == fingerprint:
            print(f"[SECOES CACHE] {uf}")
            results[source.name] = old
            continue
        report = ingest_archive(source, year, target)
        report["fingerprint"] = fingerprint
        report["sha256"] = cli.hash_file(source)
        results[source.name] = report
        print(f"[SECOES OK] {uf}: {report['linhas_origem']:,} registros de origem")
    catalog = {"ano": year, "revisao": REVISION, "fontes": results}
    tmp = manifest_path.with_suffix(".part.json")
    try:
        tmp.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, manifest_path)
    finally:
        tmp.unlink(missing_ok=True)
    return catalog


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Prepara os dados por secao no Atlas")
    parser.add_argument("--year", type=int, default=2026)
    args = parser.parse_args(argv)
    prepare_sections(args.year)


if __name__ == "__main__":
    main()
