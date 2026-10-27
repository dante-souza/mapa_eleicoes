"""Mapas de delta: alternância sem recarga nem milhares de marcadores."""
import folium
import geopandas as gpd
from shapely.geometry import Polygon

from mapa_eleicoes.swing_layers import _arrow_geometry, delta_map


def sample():
    geo = gpd.GeoDataFrame(
        {"_key": ["3550308", "3509502"]},
        geometry=[
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            Polygon([(1, 0), (2, 0), (2, 1), (1, 1)]),
        ],
        crs="EPSG:4326",
    )
    geo["_vote"] = [
        {
            "municipio": "Cidade 1", "delta": 30,
            "saldo_1t": -20, "saldo_2t": 10, "delta_a": 40,
            "delta_b": 10, "virada": "Para A",
        },
        None,
    ]
    return geo


def polygon_properties(mapa):
    """Read native GeoJSON, independent of Folium's Unicode escaping in HTML."""
    layers = [child for child in mapa._children.values()
              if isinstance(child, folium.GeoJson)]
    assert len(layers) == 1
    return [feature["properties"] for feature in layers[0].data["features"]]


def test_two_overlays_are_exclusive_and_tiles_remain_visible():
    mapa = delta_map(sample())
    groups = [c for c in mapa._children.values() if isinstance(c, folium.FeatureGroup)]
    assert [(g.layer_name, g.show) for g in groups] == [
        ("Divisões + setas", True),
        ("Áreas por delta (sem setas)", False),
    ]
    html = mapa.get_root().render()
    assert 'map.on("overlayadd"' in html
    assert 'map.on("overlayremove"' in html
    assert "municipal.setStyle(" in html
    assert "map.on(\"zoomend\", sync)" in html
    assert "zoom < low" in html
    assert "zoom >= high" in html
    assert "openstreetmap.org" in html
    # Somente uma malha de polígonos e uma camada GeoJSON de setas.
    assert html.count("L.geoJson(") == 2
    assert "L.marker(" not in html
    props = polygon_properties(mapa)
    assert len(props) == 2
    missing = [prop for prop in props if not prop["com_dados"]]
    assert len(missing) == 1
    assert missing[0]["regiao"] == "Sem dados comparáveis"
    assert missing[0]["delta"] == "—"


def test_arrow_geometry_is_directional_without_markers():
    point = sample().geometry.iloc[0].representative_point()
    nw = _arrow_geometry(point, 30, 30, (0, 0, 1, 1))
    ne = _arrow_geometry(point, -30, 30, (0, 0, 1, 1))
    assert nw["type"] == "MultiLineString"
    assert len(nw["coordinates"]) == 3
    assert nw["coordinates"][0][1][0] < point.x
    assert ne["coordinates"][0][1][0] > point.x


def test_missing_vote_does_not_make_arrow():
    geo = sample()
    geo["_vote"] = [None, None]
    mapa = delta_map(geo)
    html = mapa.get_root().render()
    assert html.count("L.geoJson(") == 1
    props = polygon_properties(mapa)
    assert len(props) == 2
    assert all(prop["regiao"] == "Sem dados comparáveis" for prop in props)
    assert all(prop["com_dados"] is False for prop in props)
    assert all(prop["delta"] == "—" for prop in props)


def test_state_arrow_is_aggregated_one_per_uf():
    from mapa_eleicoes.swing_layers import _state_arrows
    frame = sample()
    report = [
        dict(uf="SP", delta=30, virada="Para A", municipios_comparaveis=2),
    ]
    features = _state_arrows(frame, report)["features"]
    assert len(features) == 1
    assert features[0]["properties"]["regiao"].startswith("UF SP")
    assert features[0]["properties"]["delta"] == "+30"
    # Nenhuma seta adicional para município sem votos do 2º turno.
    assert features[0]["geometry"]["type"] == "MultiLineString"


def test_zoom_switches_to_prepared_zones_without_reloading_tiles():
    zone = gpd.GeoDataFrame(
        {"_key": ["SP:100:1"]},
        geometry=[Polygon([(0, 0), (.5, 0), (.5, .5), (0, .5)])],
        crs="EPSG:4326",
    )
    zone["_vote"] = [{
        "uf": "SP", "municipio": "Cidade 1", "zona": 1, "delta": -10,
        "saldo_1t": 20, "saldo_2t": 10, "delta_a": 0,
        "delta_b": 10, "virada": "Sem virada",
    }]
    mapa = delta_map(
        sample(), zones=zone,
        states=[dict(uf="SP", delta=30, virada="Para A", municipios_comparaveis=2)],
    )
    html = mapa.get_root().render()
    assert "zoneActive" in html
    assert "map.on(\"zoomend\", sync)" in html
    assert "Setas estaduais" in html
    assert "Setas municipais" in html
    assert "Setas zonais" in html
    assert "zonas" not in str(mapa.location)  # inicialização geográfica normal
    assert html.count("L.geoJson(") == 5
    assert "L.marker(" not in html


def test_navigation_labels_main_page_without_renaming_existing_app():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    router = (root / "atlas.py").read_text(encoding="utf-8")
    makefile = (root / "Makefile").read_text(encoding="utf-8")
    assert 'st.Page("app.py", title="Atlas Eleitoral"' in router
    assert 'st.Page("pages/1_Deltas_e_viradas.py", title="Deltas e viradas"' in router
    assert makefile.count("-m streamlit run atlas.py") == 2
