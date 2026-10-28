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
    assert 'featureLayer.on("click"' in html and "fitBounds" in html
    # Também aceita cliques do mapa quando o renderer Canvas não envia o
    # evento para a feição (e.sourceTarget sem dados do polígono).
    assert 'map.on("click", function (e)' in html
    assert "cityAt(e.latlng)" in html
    assert 'layer.on("click"' not in html
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


def test_back_control_esc_and_dark_backdrop():
    from mapa_eleicoes.map_focus import FocusBackdrop
    fmap = folium.Map(location=[0, 0])
    layer = folium.GeoJson(FC).add_to(fmap)
    fmap.add_child(CityFocus(layer))
    html = fmap.get_root().render()
    assert "Voltar ao mapa completo" in html and '"Escape"' in html
    # O estilo atual aprovado usa .12; .25 era expectativa antiga do teste.
    assert ".atlas-focus .leaflet-tile-pane { filter: brightness(.12)" in html
    single = folium.Map(location=[0, 0])
    single.add_child(FocusBackdrop())
    assert '"atlas-focus")' in single.get_root().render()


def test_focus_restores_selected_city_after_streamlit_rerun():
    fmap = folium.Map(location=[0, 0])
    layer = folium.GeoJson(FC).add_to(fmap)
    fmap.add_child(CityFocus(layer, initial_focus="3550308"))
    html = fmap.get_root().render()
    # O ID persiste no callback Python; a câmera é restaurada no navegador
    # depois do fitBounds inicial do Folium, não antes.
    assert "INITIAL_CITY" in html
    assert '"3550308"' in html
    assert 'featureLayer.on("click"' in html
    assert "setFocus(INITIAL_CITY)" in html
    assert "map.fitBounds(previous.getBounds()" in html


def test_focus_does_not_auto_zoom_without_saved_city():
    fmap = folium.Map(location=[0, 0])
    layer = folium.GeoJson(FC).add_to(fmap)
    fmap.add_child(CityFocus(layer))
    html = fmap.get_root().render()
    assert "INITIAL_CITY = null" in html
    assert 'featureLayer.on("click"' in html
    # Não depende de e.layer (pode estar ausente num clique propagado).
    assert "idOf(e.layer)" not in html


def test_streamlit_folium_keeps_focus_code_in_component_javascript():
    """Full Folium HTML passing is not enough: test the Streamlit bridge too."""
    from streamlit_folium import generate_leaflet_string

    fmap = folium.Map(location=[0, 0])
    layer = folium.GeoJson(FC).add_to(fmap)
    fmap.add_child(CityFocus(layer, initial_focus="3550308"))
    fmap.get_root().render()
    component_js = generate_leaflet_string(fmap)
    assert 'featureLayer.on("click"' in component_js
    assert 'map.on("click", function (e)' in component_js
    assert "map.fitBounds(featureLayer.getBounds()" in component_js
    assert "setFocus(INITIAL_CITY)" in component_js


def test_restored_city_keeps_original_bounds_for_back_control():
    fmap = folium.Map(location=[0, 0])
    layer = folium.GeoJson(FC).add_to(fmap)
    full = [[-26.0, -50.0], [-20.0, -41.0]]
    fmap.add_child(CityFocus(
        layer, initial_focus="3550308", home_bounds=full,
    ))
    html = fmap.get_root().render()
    assert "ORIGINAL_BOUNDS" in html
    assert "L.latLngBounds(ORIGINAL_BOUNDS)" in html
    assert "if (home === null) { home = map.getBounds(); }" in html
    assert "before = home;" in html
    assert '"Voltar ao mapa completo"' in html or "Voltar ao mapa completo" in html
