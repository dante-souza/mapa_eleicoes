"""Detalhes por zoom no navegador: nada de zoom/pan volta ao Streamlit."""
from __future__ import annotations

import folium
import pytest

from mapa_eleicoes.map_navigation import SITE_ZOOM, ZONE_ZOOM
from mapa_eleicoes.map_panes import (
    DISTRICT_PANE, SITE_PANE, ZONE_PANE, ClusterAssets, ZoomPanes, explorer_gates,
)


def test_automatic_mode_gates_zones_then_sites():
    assert explorer_gates("Automático") == {ZONE_PANE: ZONE_ZOOM, SITE_PANE: SITE_ZOOM}
    # Modos explicitos: a camera escolhida fica sempre visivel.
    assert explorer_gates("Seção eleitoral (locais)")[SITE_PANE] is None
    assert explorer_gates("Zona eleitoral (aproximada)")[DISTRICT_PANE] is None


def test_panes_created_before_layers_with_svg_and_zoom_handler():
    fmap = folium.Map(location=[0, 0], prefer_canvas=True)
    fmap.add_child(ZoomPanes(explorer_gates("Automático")))
    folium.GeoJson(
        {"type": "FeatureCollection", "features": []}, pane=ZONE_PANE,
    ).add_to(fmap)
    html = fmap.get_root().render()
    assert html.index("createPane") < html.index("L.geoJson(")
    assert "L.svg({pane: spec.name})" in html
    assert 'map.on("zoomend", sync)' in html
    assert ".atlas-detail-pane > svg { pointer-events: none; }" in html
    assert f'"min": {ZONE_ZOOM}' in html


def test_unknown_pane_rejected():
    with pytest.raises(ValueError):
        ZoomPanes({"outro": 3})


def test_cluster_script_loaded_with_base_map():
    # Locais chegam depois, em camada dinamica: o script ja deve estar na pagina.
    fmap = folium.Map(location=[0, 0])
    fmap.add_child(ClusterAssets())
    html = fmap.get_root().render()
    assert "leaflet.markercluster.js" in html
