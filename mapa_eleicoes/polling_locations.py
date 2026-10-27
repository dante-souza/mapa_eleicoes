"""Localizacao oficial dos locais de votacao no mapa por secao.

Arquivo independente do voto, divulgado pelo TSE. Uma ou varias secoes
compartilham a mesma coordenada do LOCAL, nao existe poligono de secao.
Quando ausente/invalida, a secao segue tabulada, sem ponto artificial.
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
from mapa_eleicoes.geography import download

SOURCE_URL = (
    "https://cdn.tse.jus.br/estatistica/sead/odsele/"
    "eleitorado_locais_votacao/eleitorado_local_votacao_{year}.zip"
)
REVISION = 1
FIELDS = (
    "NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO",
    "NR_LOCAL_VOTACAO", "NM_LOCAL_VOTACAO", "DS_ENDERECO",
    "NR_LATITUDE", "NR_LONGITUDE",
)
JOIN = ("uf", "cd_municipio_tse", "zona", "secao", "turno")


def _coord(value: object, *, longitude: bool = False) -> float | None:
    try:
        coordinate = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    lower, upper = (-74.1, -29.0) if longitude else (-34.1, 6.0)
    if coordinate < lower or coordinate > upper or coordinate != coordinate:
        return None
    return coordinate


def normalize_location(row: dict) -> dict | None:
    """Registros de locais TSE com identificadores completos e geolocalizacao."""
    try:
        uf = str(row["SG_UF"]).strip().upper()
        tse = str(row["CD_MUNICIPIO"]).strip().lstrip("0") or "0"
        zone = int(row["NR_ZONA"])
        secao = int(row["NR_SECAO"])
        turno = int(row["NR_TURNO"])
        local = str(row.get("NR_LOCAL_VOTACAO", "")).strip()
        latitude = _coord(row.get("NR_LATITUDE"))
        longitude = _coord(row.get("NR_LONGITUDE"), longitude=True)
    except (KeyError, ValueError, TypeError):
        return None
    if len(uf) != 2 or not uf.isalpha() or not tse.isdigit() or zone <= 0 or secao <= 0:
        return None
    if turno not in (1, 2) or latitude is None or longitude is None:
        return None
    return {
        "uf": uf, "cd_municipio_tse": tse, "zona": zone,
        "secao": secao, "turno": turno,
        "local": local, "nome_local": str(row.get("NM_LOCAL_VOTACAO", "")).strip(),
        "endereco": str(row.get("DS_ENDERECO", "")).strip(),
        "latitude": latitude, "longitude": longitude,
    }


def ingest_location_zip(source: Path, dest: Path, chunksize: int = 50_000) -> dict:
    cli.ensure_archive(source)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shards = dest.parent / "location.parts"
    if shards.exists():
        shutil.rmtree(shards)
    shards.mkdir(parents=True)
    rows, valid, parts = 0, 0, 0

    def write_location_batch(items: list[dict], part_id: int) -> None:
        # Mesmos dtypes dos resultados por secao: Polars nao deve fazer
        # coercao implicita em chaves de join, sobretudo Int16/Int32.
        typed = pl.DataFrame(items).with_columns(
            pl.col("turno").cast(pl.Int16, strict=True),
            pl.col("zona").cast(pl.Int32, strict=True),
            pl.col("secao").cast(pl.Int32, strict=True),
        )
        typed.unique(subset=list(JOIN)).write_parquet(
            shards / f"p_{part_id:07d}.parquet"
        )

    try:
        with zipfile.ZipFile(source) as archive:
            for entry in cli.candidate_csv(archive):
                with archive.open(entry) as bin_file, io.TextIOWrapper(
                    bin_file, encoding="latin-1", newline=""
                ) as source_csv:
                    reader = csv.DictReader(source_csv, delimiter=";")
                    present = set(reader.fieldnames or [])
                    needed = set(J for J in FIELDS[:5]) | {"NR_LATITUDE", "NR_LONGITUDE"}
                    if not needed.issubset(present):
                        raise ValueError(
                            f"{entry}: formato do TSE sem {sorted(needed - present)}"
                        )
                    batch = []
                    for line in reader:
                        rows += 1
                        item = normalize_location(line)
                        if item is not None:
                            batch.append(item)
                            valid += 1
                        if len(batch) >= chunksize:
                            write_location_batch(batch, parts)
                            parts += 1
                            batch.clear()
                    if batch:
                        write_location_batch(batch, parts)
                        parts += 1
        if parts == 0:
            raise ValueError("Arquivo local de votacao sem coordenadas validas")
        lazy = pl.scan_parquet(str(shards / "p_*.parquet"))
        # Nao soma coordenadas: a chave identifica a secao. Um local pode
        # receber multiplas secoes; cada uma ganha registro com mesmo ponto.
        mapped = lazy.unique(subset=list(JOIN), keep="first").sort(list(JOIN))
        tmp = dest.with_suffix(".part.parquet")
        try:
            mapped.sink_parquet(tmp, compression="zstd")
            os.replace(tmp, dest)
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        shutil.rmtree(shards, ignore_errors=True)
    return {"linhas": rows, "coordenadas_validas": valid,
            "sem_coordenadas": rows - valid, "fonte": source.name}


def prepare_locations(
    year: int, *, root: Path | None = None, source: Path | None = None,
    no_download: bool = False,
) -> dict:
    data = root or cli.DATA
    zip_path = source or data / "raw" / "reference" / f"eleitorado_local_votacao_{year}.zip"
    if not zip_path.exists():
        if no_download:
            raise FileNotFoundError(f"Falta arquivo oficial de locais TSE: {zip_path}")
        download(SOURCE_URL.format(year=year), zip_path)
    target = data / "serving" / str(year) / "locais.parquet"
    report_path = target.with_suffix(".json")
    stat = zip_path.stat()
    fingerprint = {"bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    if target.exists() and report_path.exists():
        prev = json.loads(report_path.read_text(encoding="utf-8"))
        if prev.get("fingerprint") == fingerprint and prev.get("revision") == REVISION:
            print(f"[LOCAIS CACHE] {target}")
            return prev
    report = ingest_location_zip(zip_path, target)
    report.update({
        "fingerprint": fingerprint, "sha256": cli.hash_file(zip_path),
        "revision": REVISION, "parquet": str(target),
        "origem": SOURCE_URL.format(year=year) if source is None else str(source),
    })
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[LOCAIS] {report['coordenadas_validas']:,} linhas com coordenadas")
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Georreferencia secoes por local oficial TSE")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--file", type=Path)
    parser.add_argument("--no-download", action="store_true")
    args = parser.parse_args(argv)
    prepare_locations(args.year, source=args.file, no_download=args.no_download)


if __name__ == "__main__":
    main()
