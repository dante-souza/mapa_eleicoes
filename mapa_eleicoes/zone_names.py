"""Nome APROXIMADO de zona eleitoral, derivado dos locais de votacao do TSE.

Os dados abertos do TSE trazem so o numero da zona (NR_ZONA). Os TREs
costumam nomear a zona pelo bairro ou pela cidade do cartorio, mas isso nao
vem nos arquivos. Aqui o nome e derivado, sempre rotulado como aproximado:

- zona dentro da cidade: bairro (NM_BAIRRO) com mais secoes da zona;
- zona inteira: municipio com mais secoes da zona (no interior, em geral
  a sede da comarca).

Secoes contadas uma vez (o 2o turno repete as do 1o). Empate: menor bairro
em ordem alfabetica / menor codigo de municipio.
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

SECTION = ["uf", "cd_municipio_tse", "zona", "secao"]


def zone_labels(locations: pl.DataFrame) -> tuple[dict[str, str], dict[str, str]]:
    """(bairro por 'UF:tse:zona', codigo TSE do municipio principal por 'UF:zona')."""
    if locations.is_empty() or not set(SECTION) <= set(locations.columns):
        return {}, {}
    columns = SECTION + (["bairro"] if "bairro" in locations.columns else [])
    sections = locations.select(columns).unique(subset=SECTION)
    seats = (
        sections.group_by(["uf", "zona", "cd_municipio_tse"]).len()
        .sort(["uf", "zona", "len", "cd_municipio_tse"],
              descending=[False, False, True, False])
        .unique(subset=["uf", "zona"], keep="first", maintain_order=True)
    )
    seat = {
        f"{row['uf']}:{int(row['zona'])}": str(row["cd_municipio_tse"])
        for row in seats.iter_rows(named=True)
    }
    neighborhood: dict[str, str] = {}
    if "bairro" in columns:
        tops = (
            sections.filter(pl.col("bairro").fill_null("").str.strip_chars() != "")
            .group_by(["uf", "cd_municipio_tse", "zona", "bairro"]).len()
            .sort(["uf", "cd_municipio_tse", "zona", "len", "bairro"],
                  descending=[False, False, False, True, False])
            .unique(subset=["uf", "cd_municipio_tse", "zona"], keep="first",
                    maintain_order=True)
        )
        neighborhood = {
            f"{row['uf']}:{row['cd_municipio_tse']}:{int(row['zona'])}": row["bairro"].strip()
            for row in tops.iter_rows(named=True)
        }
    return neighborhood, seat


def load_zone_labels(root: Path, year: int) -> tuple[dict[str, str], dict[str, str]]:
    path = root / "serving" / str(year) / "locais.parquet"
    if not path.is_file():
        return {}, {}
    wanted = SECTION + ["bairro"]
    present = set(pl.read_parquet_schema(path))
    return zone_labels(pl.read_parquet(path, columns=[c for c in wanted if c in present]))


def zone_label(
    uf: object, zona: object, cd_municipio_tse: object | None,
    neighborhood: dict[str, str], seat: dict[str, str], names: dict[str, str],
) -> str:
    """Nome curto: bairro (zona dentro da cidade) ou municipio principal."""
    try:
        number = int(zona)
    except (TypeError, ValueError):
        return ""
    if cd_municipio_tse is not None:
        bairro = neighborhood.get(f"{uf}:{cd_municipio_tse}:{number}")
        if bairro:
            return bairro
    code = seat.get(f"{uf}:{number}")
    return names.get(f"{uf}:{code}", "") if code else ""
