"""Navegacao por mouse, clique e escala cartografica sem navegador."""
from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from mapa_eleicoes.map_navigation import (
    SITE_ZOOM, FOCUS_ZOOM, ZONE_ZOOM, municipality_at, municipalities_in_view,
    should_render_sites, should_render_zones, state_for_municipality,
    valid_bounds, valid_position,
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
    # Clique numa cidade ja mostra as zonas; locais pedem mais zoom.
    assert ZONE_ZOOM <= FOCUS_ZOOM < SITE_ZOOM
    assert not should_render_zones(ZONE_ZOOM - 1, True)
    assert should_render_zones(ZONE_ZOOM, True)
    assert not should_render_zones(ZONE_ZOOM, False)
    assert not should_render_zones(None, True)


def test_cities_in_view_center_first_and_bounds_validated():
    shapes = geometry()
    view = {"_southWest": {"lat": -24.5, "lng": -47.5},
            "_northEast": {"lat": -21.5, "lng": -42.5}}
    center = {"lat": -22.5, "lng": -43.5}
    assert municipalities_in_view(shapes, view, center) == ["3304557", "3550308"]
    only_sp = {"_southWest": {"lat": -24, "lng": -47},
               "_northEast": {"lat": -23.2, "lng": -46.2}}
    assert municipalities_in_view(shapes, only_sp, None) == ["3550308"]
    assert municipalities_in_view(shapes, None, center) == ["3304557"]
    assert municipalities_in_view(shapes, view, center, limit=1) == ["3304557"]
    assert valid_bounds({"_southWest": {"lat": 1, "lng": 0},
                         "_northEast": {"lat": 0, "lng": 1}}) is None


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
