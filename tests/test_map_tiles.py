"""Regression coverage for Folium raster tiles.

Tiles must render without a CARTO key. Dracula styling must affect only the
raster tile pane so electoral GeoJSON polygons remain in their own colors.
"""
from __future__ import annotations

from mapa_eleicoes.map_tiles import DARK_TILE_CSS, atlas_map


def test_default_map_has_openstreetmap_attribution_and_no_carto():
    mapa = atlas_map([-15.7942, -47.8822])
    html = mapa.get_root().render()
    assert "openstreetmap.org" in html.lower()
    assert "cartocdn" not in html.lower()
    assert "cartodb" not in html.lower()
    assert "leaflet-tile-pane .leaflet-tile" in html
    assert "filter:" in html


def test_raster_css_does_not_filter_geojson_overlay():
    assert ".leaflet-tile-pane .leaflet-tile" in DARK_TILE_CSS
    assert ".leaflet-overlay-pane" not in DARK_TILE_CSS


def test_plain_map_omits_optional_dark_filter():
    mapa = atlas_map([-15.7942, -47.8822], dark=False)
    assert "leaflet-tile-pane .leaflet-tile" not in mapa.get_root().render()
