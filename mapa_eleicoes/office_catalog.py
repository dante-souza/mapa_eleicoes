"""Catalogo de cargos/turnos realmente presentes nos CSVs processados.

O painel deve oferecer cargos primeiro; depois, apenas turnos existentes
para o cargo/UF selecionados. Nenhum cargo ausente sera inventado.
Uso via Makefile: make offices ANO=2026.
"""
from __future__ import annotations

import argparse
import gzip
import unicodedata
from pathlib import Path

import polars as pl

from mapa_eleicoes import cli

# Preferencia apenas de exibicao, nao ranking de atores/candidatos.
OFFICE_SEQUENCE = (
    "presidente", "governador", "senador",
    "deputado federal", "deputado estadual", "deputado distrital",
)


def _fold(label: str) -> str:
    normalized = unicodedata.normalize("NFKD", label.strip())
    return "".join(char for char in normalized if not unicodedata.combining(char)).casefold()


def available_offices(frame: pl.DataFrame) -> list[str]:
    """Cargos presentes no recorte (ano + UF), sem filtro prematuro de turno."""
    if "cargo" not in frame.columns or frame.is_empty():
        return []
    found = frame.get_column("cargo").drop_nulls().unique().to_list()
    found = [value.strip() for value in found if isinstance(value, str) and value.strip()]
    return sorted(
        set(found),
        key=lambda value: (
            OFFICE_SEQUENCE.index(_fold(value))
            if _fold(value) in OFFICE_SEQUENCE else len(OFFICE_SEQUENCE),
            _fold(value),
            value,
        ),
    )


def available_turns(frame: pl.DataFrame, cargo: str) -> list[int]:
    """Turnos filtrados pelo cargo, nao o contrario."""
    if frame.is_empty() or not {"cargo", "turno"}.issubset(frame.columns):
        return []
    values = (
        frame.filter(pl.col("cargo") == cargo)
        .get_column("turno").drop_nulls().unique().to_list()
    )
    return sorted({int(value) for value in values})


def preferred_office(choices: list[str]) -> int:
    """Preferir Presidente quando estiver disponivel; senao, primeira opcao."""
    return next(
        (idx for idx, name in enumerate(choices) if _fold(name) == "presidente"),
        0,
    )


def office_inventory(year: int, root: Path | None = None) -> pl.DataFrame:
    """Le somente colunas relevantes de todos os CSV.gz ja processados."""
    folder = (root or cli.DATA) / "processed" / str(year)
    files = sorted(folder.glob("votos_*.csv.gz"))
    if not files:
        raise FileNotFoundError(
            f"Sem votos processados em {folder}. "
            "Use make prepare-data antes de make offices."
        )
    summaries: list[pl.DataFrame] = []
    for path in files:
        with gzip.open(path, "rb") as source:
            frame = pl.read_csv(
                source,
                columns=["uf", "cargo", "turno", "votos"],
                infer_schema=False,
            ).with_columns(
                pl.col("turno").cast(pl.Int16, strict=True),
                pl.col("votos").cast(pl.Int64, strict=True),
            )
        if frame.is_empty():
            continue
        summaries.append(
            frame.group_by(["uf", "cargo", "turno"]).agg(
                pl.len().alias("registros_agrupados"),
                pl.col("votos").sum().alias("votos_registrados"),
            ).with_columns(
                pl.lit(path.name).alias("arquivo")
            )
        )
    if not summaries:
        raise ValueError("CSV.gz encontrados, mas sem linhas para catalogo de cargos")
    return pl.concat(summaries, how="vertical").sort(
        ["turno", "cargo", "uf", "arquivo"]
    )


def print_office_inventory(year: int, root: Path | None = None) -> None:
    results = office_inventory(year, root)
    totals = results.group_by(["turno", "cargo"]).agg(
        pl.col("registros_agrupados").sum(),
        pl.col("votos_registrados").sum(),
        pl.col("uf").n_unique().alias("ufs"),
        pl.col("arquivo").n_unique().alias("arquivos"),
    ).sort(["turno", "cargo"])
    print(f"[OFFICES] Ano {year}: cargos e turnos realmente presentes nos CSV.gz")
    for item in totals.iter_rows(named=True):
        print(
            f"[OFFICES] Turno {item['turno']} / {item['cargo']}: "
            f"{item['ufs']} UFs, {item['arquivos']} arquivos, "
            f"{item['registros_agrupados']:,} linhas agregadas"
        )
    br = results.filter(pl.col("arquivo") == "votos_BR.csv.gz")
    if br.is_empty():
        print("[OFFICES] ATENCAO: votos_BR.csv.gz ausente. "
              "Confira make download UF=BR ANO=2026 e make ingest ANO=2026 UF=BR.")
    else:
        entries = [
            f"{row['cargo']} (turno {row['turno']})"
            for row in br.select(["cargo", "turno"]).unique()
                .sort(["cargo", "turno"]).iter_rows(named=True)
        ]
        print(f"[OFFICES] Fonte BR: {', '.join(entries)}")
    print(
        "[OFFICES] Nota: votos_registrados incluem cargos diferentes; "
        "nao representam eleitores unicos."
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Catalogo de cargos do TSE")
    parser.add_argument("--year", type=int, default=2026)
    args = parser.parse_args(argv)
    print_office_inventory(args.year)


if __name__ == "__main__":
    main()
