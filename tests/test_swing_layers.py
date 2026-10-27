"""Mapas de delta: alternância sem recarga nem milhares de marcadores."""
import folium
import geopandas as gpd
from shapely.geometry import Polygon

from mapa_eleicoes.swing_layers import _arrow_geometry, delta_map


def sample():
    geo = gpd.GeoDataFrame(
        {"_key": ["1000001", "1000002"]},
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
    assert "polygons.setStyle(filledStyle)" in html
    assert "polygons.setStyle(outlineStyle)" in html
    assert "openstreetmap.org" in html
    # Somente uma malha de polígonos e uma camada GeoJSON de setas.
    assert html.count("L.geoJson(") == 2
    assert "L.marker(" not in html
    assert "Sem dados comparáveis" in html


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
    assert "Sem dados comparáveis" in html
