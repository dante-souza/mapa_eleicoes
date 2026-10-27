"""Fronteira segura Polars/GeoPandas: somente escalares Python.

GeoPandas usa estruturas pandas internamente. Nunca entregar-lhe Series,
Arrow arrays ou DataFrames Polars: mapear explicitamente registros tipados.
"""
from __future__ import annotations

import re

import geopandas as gpd
import polars as pl


def ibge_code(value: object) -> str:
    """Codigo IBGE de 7 digitos, sem conversao para float ou perda de zeros."""
    if value is None:
        return ""
    code = str(value).strip()
    if re.fullmatch(r"\d+\.0+", code):
        code = code.split(".", maxsplit=1)[0]
    if not code.isdigit() or len(code) > 7:
        return ""
    return code.zfill(7)


def zone_code(uf: object, zona: object) -> str:
    """Chave eleitoral composta (UF, zona) para malhas de zonas reais."""
    code = str(zona).strip() if zona is not None else ""
    if re.fullmatch(r"\d+\.0+", code):
        code = code.split(".", maxsplit=1)[0]
    if not code.isdigit():
        return ""
    state = str(uf).strip().upper() if uf is not None else ""
    if not re.fullmatch(r"[A-Z]{2}", state):
        return ""
    return f"{state}:{int(code)}"


def add_properties(geometry: gpd.GeoDataFrame, votes: pl.DataFrame,
                   defaults: dict[str, object]) -> gpd.GeoDataFrame:
    """Junta dados em GeoPandas via dicts de escalares, evitando problemas dtype.

    Os valores vêm de Polars.iter_rows(named=True), que materializa escalares
    Python (str/int/float/None), sem pandas/Arrow/extension arrays intermediarios.
    """
    if "map_id" not in geometry.columns or "map_id" not in votes.columns:
        raise ValueError("Chave map_id ausente na malha ou nos resultados")
    records = {str(row["map_id"]): row for row in votes.iter_rows(named=True)}
    result = geometry.copy()
    for column, default in defaults.items():
        values = []
        for key in result["map_id"]:
            value = records.get(str(key), {}).get(column, default)
            values.append(default if value is None else value)
        result[column] = values
    return result
