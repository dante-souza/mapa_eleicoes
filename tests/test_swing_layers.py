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
    """Retorna propriedades municipais, mesmo com camada estadual ativa."""
    layers = [child for child in mapa._children.values()
              if isinstance(child, folium.GeoJson)]
    municipal_layers = [
        layer for layer in layers if any(
            feature["properties"].get("regiao") == "Cidade 1"
            for feature in layer.data["features"]
        )
    ]
    if municipal_layers:
        return [feature["properties"] for feature in municipal_layers[0].data["features"]]
    # O teste sem votos verifica todas as regiões, sem preferência por nomes.
    return [feature["properties"] for feature in layers[1].data["features"]]



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
    assert "syncPolygon(states, scale === \"state\"" in html
    assert 'map.on("zoomend moveend resize", sync)' in html
    assert 'if (zoom < low)' in html
    assert 'if (zoom >= high && zones)' in html
    assert "paintArrow(ctx" in html
    assert "arrowCanvas" in html
    assert "openstreetmap.org" in html
    assert 'scale === "state"' in html
    assert 'scale === "city"' in html
    # Duas malhas: estado dissolvido e municípios; setas só em Canvas.
    assert html.count("L.geoJson(") == 3
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
    assert html.count("L.geoJson(") == 3
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
    assert 'if (zoom >= high && zones)' in html
    assert 'map.on("zoomend moveend resize", sync)' in html
    assert '"state":' in html
    assert '"city":' in html
    assert '"zone":' in html
    assert 'atlas-swing-arrows' in html
    assert "zonas" not in str(mapa.location)  # inicialização geográfica normal
    assert html.count("L.geoJson(") == 4  # borda UF + 3 camadas de hover
    assert "L.marker(" not in html


def test_state_boundaries_dissolve_municipal_borders():
    from mapa_eleicoes.swing_layers import _state_geography
    report = [dict(uf="SP", delta=30, saldo_1t=-20, saldo_2t=10,
                   delta_a=40, delta_b=10, virada="Para A",
                   municipios_comparaveis=2)]
    grouped = _state_geography(sample(), report)
    assert len(grouped) == 1
    assert grouped.iloc[0]["_key"] == "SP"
    assert abs(grouped.geometry.iloc[0].area - 2.0) < 0.04
    assert grouped.iloc[0]["_vote"]["delta"] == 30


def test_arrows_are_screen_sized_and_preserve_colors():
    from mapa_eleicoes.swing_layers import _canvas_data
    assert _canvas_data(sample()) == [[0.5, 0.5, 30]]
    html = delta_map(sample()).get_root().render()
    assert 'scale === "state" ? 40' in html
    assert 'scale === "zone" ? 16' in html
    assert '"#d60828"' in html and '"#272d97"' in html
    assert 'ctx.strokeStyle = "#f8f8f2"' not in html
    assert html.count("ctx.strokeStyle =") == 1  # nenhuma borda/halo na seta
    assert "window.devicePixelRatio" in html
    assert "new Map()" in html  # redução visual de sobreposições


def test_only_state_boundaries_drawn_at_every_zoom():
    from mapa_eleicoes.swing_layers import DeltaZoomLayers
    import inspect

    source = inspect.getsource(DeltaZoomLayers)
    assert "stroke: false, weight: 0" in source  # município/zona ocultos
    assert "fillOpacity: 0.001" in source  # captura do hover preservada
    assert "syncPolygon(states, scale === \"state\"" in source
    assert "syncPolygon(cities, scale !== \"state\"" in source
    # A borda estadual fica numa camada própria, sempre ligada;
    # os dois modos de delta usam a mesma geometria de hover.
    fmap = delta_map(sample())
    layers = [child for child in fmap._children.values()
              if isinstance(child, folium.GeoJson)]
    assert len(layers) == 3
    border = layers[-1]
    assert border.options.get("interactive") is False
    assert border._style is not None
    assert 'interactive": false' in fmap.get_root().render()
    assert "map.on(\"zoomend moveend resize\", sync)" in fmap.get_root().render()


def test_state_border_ignores_internal_holes_from_simplified_municipalities():
    from mapa_eleicoes.swing_layers import _state_border_geography
    donut = Polygon(
        [(0, 0), (4, 0), (4, 4), (0, 4)],
        holes=[[(1, 1), (3, 1), (3, 3), (1, 3)]],
    )
    regions = gpd.GeoDataFrame(
        {"_key": ["SP"], "_vote": [None]},
        geometry=[donut], crs="EPSG:4326",
    )
    outline = _state_border_geography(regions)
    assert len(outline) == 1
    assert len(outline.geometry.iloc[0].interiors) == 0


def test_original_map_page_runs_as_classic_streamlit_homepage():
    """Prevent a st.navigation router from changing the main map lifecycle."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    homepage = (root / "Atlas_Eleitoral.py").read_text(encoding="utf-8")
    makefile = (root / "Makefile").read_text(encoding="utf-8")
    app = (root / "app.py").read_text(encoding="utf-8")

    assert "st.navigation(" not in homepage
    assert "st.Page(" not in homepage
    assert 'with_name("app.py")' in homepage
    assert 'exec(compile(' in homepage
    assert not (root / "atlas.py").exists()
    assert makefile.count("-m streamlit run Atlas_Eleitoral.py") == 2
    assert 'CityFocus(results_layer, initial_focus=selected_city)' in app
    assert "render_explorer(" in app
    assert (root / "pages" / "1_Deltas_e_viradas.py").is_file()
