"""Navegacao por mouse, clique e escala cartografica sem navegador."""
from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from mapa_eleicoes.map_navigation import (
    SITE_ZOOM, FOCUS_ZOOM, ZONE_ZOOM, municipality_at, should_render_sites,
    state_for_municipality, valid_position, zoom_for_bounds,
)


def geometry():
    return gpd.GeoDataFrame(
        {
            "map_id": ["3550308", "3304557"],
            "geometry": [
                Polygon([(-47, -24), (-46, -24), (-46, -23), (-47, -23)]),
                Polygon([(-44, -23), (-43, -23), (-43, -22), (-44, -22)]),
            ],
        },
        crs="EPSG:4326",
    )


def test_mouse_position_selects_real_municipal_polygon_only():
    shapes = geometry()
    assert municipality_at(shapes, {"lat": -23.5, "lng": -46.5}) == "3550308"
    assert municipality_at(shapes, {"lat": -22.5, "lng": -43.5}) == "3304557"
    assert municipality_at(shapes, {"lat": -20, "lng": -40}) is None
    assert municipality_at(shapes, {"lat": "x", "lng": -46}) is None


def test_edge_uses_polygon_covers_without_inventing_nearest_city():
    shapes = geometry()
    assert municipality_at(shapes, {"lat": -23.5, "lng": -46.0}) == "3550308"
    assert municipality_at(shapes, {"lat": -25, "lng": -46.5}) is None


def test_drilldown_order_municipio_zona_local():
    # Municipio -> zonas -> locais, cada nivel com mais zoom.
    assert ZONE_ZOOM <= FOCUS_ZOOM < SITE_ZOOM


def test_zoom_for_bounds_frames_city_and_country():
    # Sao Paulo (capital): ~0,5 x 0,65 grau cabe em zoom 10 num mapa de 700 px.
    assert zoom_for_bounds((-46.83, -24.01, -46.36, -23.36), height=700) == 10
    # Brasil inteiro: zoom de pais, limitado pelo minimo.
    assert zoom_for_bounds((-74, -34, -34, 5.3), height=700) == 4
    # Cidade minuscula nao passa do zoom maximo.
    assert zoom_for_bounds((-46.6, -23.5, -46.5999, -23.4999)) == 15
    assert zoom_for_bounds((1, 0, 0, 1)) == 4


def test_section_pins_appear_only_after_urban_zoom():
    assert not should_render_sites(5, True)
    assert not should_render_sites(SITE_ZOOM - 1, True)
    assert should_render_sites(SITE_ZOOM, True)
    assert should_render_sites(SITE_ZOOM + 2, True)
    assert not should_render_sites(SITE_ZOOM + 2, False)
    assert not should_render_sites(None, True)


def test_uf_derived_from_ibge_code_not_current_sidebar():
    assert state_for_municipality("3550308") == "SP"
    assert state_for_municipality("3304557") == "RJ"
    assert state_for_municipality("5300108") == "DF"
    assert state_for_municipality("random") is None


def test_invalid_mouse_payload_is_rejected():
    for wrong in (None, {}, {"lat": 100, "lng": 0},
                  {"lat": float("nan"), "lng": -46},
                  {"lat": -23.5, "lng": 500}):
        assert valid_position(wrong) is None
