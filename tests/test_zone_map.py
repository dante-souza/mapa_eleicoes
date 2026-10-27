"""Camada Folium das areas aproximadas de zona."""
from __future__ import annotations

import folium
import geopandas as gpd
import polars as pl
from shapely.geometry import box

from mapa_eleicoes.vote_gradients import margin_shade
from mapa_eleicoes.zone_map import zone_layer, zone_results


def areas():
    return gpd.GeoDataFrame(
        {
            "map_id": ["SP:71072:1", "SP:71072:2", "SP:62910:5"],
            "uf": ["SP"] * 3,
            "cd_municipio_tse": ["71072", "71072", "62910"],
            "codigo_ibge": ["3550308", "3550308", "3509502"],
            "zona": [1, 2, 5],
            "n_zonas_municipio": [2, 2, 1],
        },
        geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1), box(5, 5, 6, 6)],
        crs="EPSG:4326",
    )


def votes():
    rows = [
        ("SP", "71072", "SÃO PAULO", 1, "13", "LULA", "nominal", 70),
        ("SP", "71072", "SÃO PAULO", 1, "22", "FLAVIO", "nominal", 30),
        ("SP", "71072", "SÃO PAULO", 2, "13", "LULA", "nominal", 48),
        ("SP", "71072", "SÃO PAULO", 2, "22", "FLAVIO", "nominal", 52),
        ("SP", "62910", "CAMPINAS", 5, "13", "LULA", "nominal", 10),
    ]
    return pl.DataFrame(
        rows, orient="row",
        schema=["uf", "cd_municipio_tse", "municipio", "zona",
                "numero", "candidato", "tipo_voto", "votos"],
    ).with_columns(pl.col("zona").cast(pl.Int32))


def render(layer):
    fmap = folium.Map(location=[0, 0])
    layer.add_to(fmap)
    return fmap.get_root().render()


def test_zone_results_keys_match_area_ids():
    results = zone_results(votes())
    assert set(results["map_id"]) == {"SP:71072:1", "SP:71072:2", "SP:62910:5"}


def test_layer_colors_by_margin_and_skips_single_zone_cities():
    layer, count = zone_layer(
        areas(), votes(), names={"SP:71072": "SÃO PAULO"}
    )
    # Campinas tem uma unica zona: repetiria o municipio, entao fica fora.
    assert count == 2
    html = render(layer)
    assert "Zona 1 \\u00b7 S\\u00c3O PAULO (SP)" in html
    assert "aproximada" in html
    assert margin_shade("13", 40) in html      # zona 1: LULA +40 p.p.
    assert margin_shade("22", 4) in html       # zona 2: FLAVIO +4 p.p.


def test_candidate_mode_and_empty_inputs():
    layer, count = zone_layer(areas(), votes(), selected_number="13")
    assert count == 2 and "(% v" in render(layer)
    assert zone_layer(areas(), votes().clear()) == (None, 0)
    assert zone_layer(areas().iloc[0:0], votes()) == (None, 0)
