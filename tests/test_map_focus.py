"""Foco de cidade como no g1: a cidade acende e o resto apaga, no navegador."""
from __future__ import annotations

import folium

from mapa_eleicoes.map_focus import DIM_STYLE, CityFocus, context_layer

FC = {"type": "FeatureCollection", "features": [{
    "type": "Feature", "properties": {"map_id": "3550308"},
    "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
}]}


def test_focus_wraps_layer_style_and_reacts_to_click_and_zoom():
    fmap = folium.Map(location=[0, 0])
    layer = folium.GeoJson(FC, style_function=lambda _: {"fillColor": "#d60828"}).add_to(fmap)
    fmap.add_child(CityFocus(layer))
    html = fmap.get_root().render()
    # Estilo da propria camada: o resetStyle do hover preserva o apagado.
    assert "layer.options.style = styleFor" in html
    assert 'layer.on("click"' in html and "fitBounds" in html
    assert 'map.on("moveend"' in html
    assert DIM_STYLE["fillColor"] in html
    assert html.index("L.geoJson(") < html.index("styleFor")
    assert layer.get_name() in html.split("styleFor")[-1]


def test_context_layer_is_dim_and_not_interactive():
    fmap = folium.Map(location=[0, 0])
    context_layer(FC).add_to(fmap)
    html = fmap.get_root().render()
    assert '"interactive": false' in html
    assert DIM_STYLE["fillColor"] in html
