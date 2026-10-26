"""Regressoes na fronteira de dtypes Polars/GeoPandas."""
from __future__ import annotations

import json

import geopandas as gpd
import polars as pl
from shapely.geometry import Point

from mapa_eleicoes.geo_bridge import add_properties, ibge_code, zone_code


def test_ibge_code_keeps_seven_digits():
    assert ibge_code("0140010") == "0140010"
    assert ibge_code("1400100.0") == "1400100"
    assert ibge_code(1400100) == "1400100"
    assert ibge_code(None) == ""
    assert ibge_code("unknown") == ""


def test_zone_key_normalizes_number_without_floating_precision():
    assert zone_code("rr", "001") == "RR:1"
    assert zone_code("RR", "1.0") == "RR:1"
    assert zone_code("RR", None) == ""


def test_polars_geopandas_geojson_boundary_with_int64_and_nulls():
    geometry = gpd.GeoDataFrame(
        {"map_id": ["0140010", "1400100", "1400209"],
         "geometry": [Point(-60.0, 2.0), Point(-61.0, 3.0), Point(-62.0, 4.0)]},
        geometry="geometry", crs="EPSG:4326",
    )
    votes = pl.DataFrame({
        "map_id": ["0140010", "1400100"],
        "candidato": ["EXEMPLO A", None],
        "numero": ["013", "22"],
        "votos": [3000000000, 42],
        "pct": [70.25, 29.75],
    }).with_columns(pl.col("votos").cast(pl.Int64))
    joined = add_properties(geometry, votes, {
        "candidato": "Sem dados",
        "numero": "",
        "votos": 0,
        "pct": 0.0,
    })
    assert joined.loc[0, "votos"] == 3000000000
    assert joined.loc[0, "numero"] == "013"
    assert joined.loc[1, "candidato"] == "Sem dados"
    assert joined.loc[2, "votos"] == 0
    doc = json.loads(joined.to_json(drop_id=True))
    assert doc["features"][0]["properties"]["votos"] == 3000000000
    assert doc["features"][0]["properties"]["numero"] == "013"
    assert doc["features"][1]["properties"]["candidato"] == "Sem dados"
