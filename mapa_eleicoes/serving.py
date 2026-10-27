"""Materializacao de dados prontos para consulta no Atlas.

Nunca mistura Parquets auxiliares munzona com totais por secao.
CSV.gz eh a fonte derivada auditavel; o Streamlit so consome os
Parquets de serving validados e seu catalogo de cargos/turnos.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from mapa_eleicoes import cli


SERVE_REV = 1
TEXT_COLUMNS = [
    "uf", "cd_municipio_tse", "municipio",
    "cargo", "numero", "candidato", "tipo_voto",
]
COLUMNS = [
    "ano", "turno", "uf", "cd_municipio_tse", "municipio",
    "zona", "cargo", "numero", "candidato", "tipo_voto", "votos",
]


def read_aggregate(path: Path) -> pl.DataFrame:
    with gzip.open(path, "rb") as input_file:
        df = pl.read_csv(input_file, infer_schema=False)
    missing = set(COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"{path.name}: faltam colunas {sorted(missing)}")
    return df.select(COLUMNS).with_columns(
        pl.col("ano").cast(pl.Int32, strict=True),
        pl.col("turno").cast(pl.Int16, strict=True),
        pl.col("zona").cast(pl.Int32, strict=True),
        pl.col("votos").cast(pl.Int64, strict=True),
        *[pl.col(column).fill_null("").cast(pl.String) for column in TEXT_COLUMNS],
    )


def prepare_serving(year: int, root: Path | None = None) -> dict:
    data = root or cli.DATA
    processed = data / "processed" / str(year)
    source_files = sorted(processed.glob("votos_*.csv.gz"))
    if not source_files:
        raise FileNotFoundError(
            f"Sem resultados para consumo em {processed}; execute a preparacao dos ZIPs."
        )
    output = data / "serving" / str(year)
    output.mkdir(parents=True, exist_ok=True)
    old_manifest = output / "catalog.json"
    old = {}
    if old_manifest.is_file():
        try:
            old = json.loads(old_manifest.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            old = {}
    old_sources = old.get("fontes", {}) if old.get("revisao") == SERVE_REV else {}
    sources = {}
    inventory = []
    for src in source_files:
        parquet_name = src.name.replace(".csv.gz", ".parquet")
        dest = output / parquet_name
        st = src.stat()
        previous = old_sources.get(src.name, {})
        fingerprint = {"bytes": st.st_size, "mtime_ns": st.st_mtime_ns}
        cache_hit = (
            previous.get("fingerprint") == fingerprint
            and dest.is_file()
        )
        if cache_hit:
            source_report = dict(previous)
            print(f"[SERVE CACHE] {src.name}")
        else:
            frame = read_aggregate(src)
            if frame.is_empty():
                raise ValueError(f"{src.name}: sem registros processados")
            if bool((frame["votos"] < 0).any()):
                raise ValueError(f"{src.name}: votos negativos")
            meta = processed / src.name.replace(".csv.gz", ".json")
            if meta.is_file():
                source_meta = json.loads(meta.read_text(encoding="utf-8"))
                expected = source_meta.get("total_votos_linhas")
                if expected is not None and int(frame["votos"].sum()) != int(expected):
                    raise ValueError(f"{src.name}: total difere do manifesto original")
            part = dest.with_name(dest.name + ".part")
            try:
                frame.write_parquet(part, compression="zstd")
                os.replace(part, dest)
            finally:
                part.unlink(missing_ok=True)
            combinations = (
                frame.group_by(["cargo", "turno"]).agg(
                    pl.len().alias("registros"),
                    pl.col("votos").sum().alias("votos"),
                    pl.col("uf").n_unique().alias("ufs"),
                )
                .sort(["cargo", "turno"]).to_dicts()
            )
            source_report = {
                "fingerprint": fingerprint,
                "sha256": cli.hash_file(src),
                "linhas": frame.height,
                "total_votos": int(frame["votos"].sum()),
                "cargos_turnos": combinations,
                "parquet": parquet_name,
            }
            print(f"[SERVE OK] {parquet_name}: {frame.height:,} linhas")
        sources[src.name] = source_report
        for entry in source_report["cargos_turnos"]:
            inventory.append({
                "arquivo": src.name,
                "cargo": entry["cargo"],
                "turno": entry["turno"],
                "ufs": entry["ufs"],
                "registros": entry["registros"],
            })
    # Parquets removidos das fontes nao devem continuar disponiveis.
    active = {item["parquet"] for item in sources.values()}
    for leftover in output.glob("votos_*.parquet"):
        if leftover.name not in active:
            leftover.unlink()
    geo = data / "geo" / "municipios.geojson"
    crosswalk = data / "reference" / "tse_ibge.csv"
    catalog = {
        "revisao": SERVE_REV,
        "ano": year,
        "gerado_utc": datetime.now(timezone.utc).isoformat(),
        "fontes": sources,
        "cargos_turnos": inventory,
        "geografia": {
            "municipios": geo.is_file(),
            "de_para": crosswalk.is_file(),
            "zonas_poligonos": (data / "geo" / "zonas.geojson").is_file(),
        },
        "observacao": (
            "Cargos/turnos indicam somente o que consta nos arquivos locais; "
            "o catalogo nao atribui dados faltantes a turnos eleitorais."
        ),
    }
    temporary = old_manifest.with_suffix(".part.json")
    try:
        temporary.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, old_manifest)
    finally:
        temporary.unlink(missing_ok=True)
    print(
        f"[SERVE] {len(sources)} bases prontas em {output}; "
        f"malha municipal={catalog['geografia']['municipios']}; "
        f"crosswalk={catalog['geografia']['de_para']}; "
        f"zonas={catalog['geografia']['zonas_poligonos']}"
    )
    return catalog


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Prepara dataset final para o mapa")
    parser.add_argument("--year", type=int, default=2026)
    args = parser.parse_args(argv)
    prepare_serving(args.year)


if __name__ == "__main__":
    main()
