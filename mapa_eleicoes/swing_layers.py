"""Mapa hierárquico de deltas: estados -> municípios -> zonas pelo zoom.

Mapa e seleção de camadas rodam inteiramente no Leaflet. O Streamlit não
recebe zoom/centro do cliente. Apenas geometria oficial municipal e
aproximações de zona produzidas pelo pipeline do Atlas são representadas.
"""
from __future__ import annotations

from collections import defaultdict
from html import escape
import json
from math import sqrt

import folium
import geopandas as gpd
import shapely
from branca.element import MacroElement
from jinja2 import Template

from mapa_eleicoes.geo_payload import BoundedGeoJson, leaflet_bounds, rounded_geometries
from mapa_eleicoes.map_tiles import atlas_map
from mapa_eleicoes.party_colors import PL_BLUE, PT_RED
from mapa_eleicoes.zone_geometry import UF_PREFIX

NEUTRAL = "#6272a4"
BORDER = "#a6a6b5"
NO_DATA = "#44475a"
STATE_MAX_ZOOM = 7      # zoom < 7: uma seta por UF
ZONE_MIN_ZOOM = 11     # zoom >= 11: zonas, quando há geometria preparada


class DeltaZoomLayers(MacroElement):
    """Escalas territoriais exclusivas e setas Canvas em pixels da tela.

    Tudo roda no Leaflet. Não publica eventos de zoom para Streamlit e não
    interfere no mapa principal de apuração.
    """

    _template = Template("""
    {% macro script(this, kwargs) %}
    (function(map, outlines, filled, states, cities, zones, data, low, high) {
        var arrowCanvas = L.DomUtil.create("canvas", "atlas-swing-arrows",
                                            map.getPanes().overlayPane);
        arrowCanvas.style.cssText = "position:absolute;pointer-events:none;z-index:430;";
        var ratio = Math.min(window.devicePixelRatio || 1, 2);
        var lastMode = null;

        function transparent(layer, level) {
            return {
                fillOpacity: 0,
                color: level === "state" ? "#e0e0e8" : "#a6a6b5",
                weight: level === "state" ? 1.5 : 0.8
            };
        }
        function painted(feature, level) {
            return {
                fillColor: feature.properties.cor,
                fillOpacity: feature.properties.com_dados ? 0.72 : 0,
                color: level === "state" ? "#d8d8df" : "#181820",
                weight: level === "state" ? 1.5 : 0.55
            };
        }
        function syncPolygon(layer, visible, level, colored) {
            if (!layer) { return; }
            if (visible && !map.hasLayer(layer)) { map.addLayer(layer); }
            if (!visible && map.hasLayer(layer)) { map.removeLayer(layer); }
            if (visible) {
                layer.setStyle(function(f) {
                    return colored ? painted(f, level) : transparent(f, level);
                });
            }
        }
        function scaleForZoom() {
            var zoom = map.getZoom();
            if (zoom < low) { return "state"; }
            if (zoom >= high && zones) { return "zone"; }
            return "city";
        }
        function paintArrow(ctx, x, y, delta, magnitude, scale) {
            var direction = delta > 0 ? -1 : 1;
            var relative = Math.sqrt(magnitude);
            var len = (scale === "state" ? 40 : scale === "zone" ? 16 : 21) +
                      (scale === "state" ? 28 : scale === "zone" ? 11 : 16) * relative;
            var lineWidth = scale === "state" ? 4.6 : scale === "zone" ? 2.4 : 3.0;
            var dx = direction * len * 0.72, dy = -len * 0.72;
            var tipX = x + dx, tipY = y + dy;
            var head = len * 0.32;
            var angle = Math.atan2(dy, dx);
            function shape() {
                ctx.beginPath();
                ctx.moveTo(x, y);
                ctx.lineTo(tipX, tipY);
                ctx.lineTo(tipX - head * Math.cos(angle - Math.PI / 6),
                           tipY - head * Math.sin(angle - Math.PI / 6));
                ctx.moveTo(tipX, tipY);
                ctx.lineTo(tipX - head * Math.cos(angle + Math.PI / 6),
                           tipY - head * Math.sin(angle + Math.PI / 6));
                ctx.stroke();
            }
            ctx.lineCap = "round";
            ctx.lineJoin = "round";
            // Halo escuro para contraste tanto sobre a base quanto sobre o
            // preenchimento, sem alterar o vermelho/azul do Atlas.
            ctx.strokeStyle = "#14141b";
            ctx.lineWidth = lineWidth + 3.3;
            shape();
            ctx.strokeStyle = delta > 0 ? "#d60828" : "#272d97";
            ctx.lineWidth = lineWidth;
            shape();
        }
        function redraw() {
            var size = map.getSize();
            var topLeft = map.containerPointToLayerPoint([0, 0]);
            arrowCanvas.style.left = topLeft.x + "px";
            arrowCanvas.style.top = topLeft.y + "px";
            arrowCanvas.style.width = size.x + "px";
            arrowCanvas.style.height = size.y + "px";
            arrowCanvas.width = Math.round(size.x * ratio);
            arrowCanvas.height = Math.round(size.y * ratio);
            var ctx = arrowCanvas.getContext("2d");
            ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
            if (!map.hasLayer(outlines)) { return; }
            var scale = scaleForZoom();
            var items = data[scale] || [];
            var maximum = 1;
            items.forEach(function(row) {
                maximum = Math.max(maximum, Math.abs(row[2]));
            });
            // Em áreas muito densas, prioriza a maior magnitude dentro de
            // cada célula visual, sem modificar cálculos ou dados oficiais.
            var cell = scale === "state" ? 9 : scale === "zone" ? 16 : 21;
            var visible = new Map();
            items.forEach(function(row) {
                if (!row[2]) { return; }
                var point = map.latLngToContainerPoint([row[0], row[1]]);
                if (point.x < -85 || point.y < -85 ||
                    point.x > size.x + 85 || point.y > size.y + 85) { return; }
                var key = Math.floor(point.x / cell) + ":" +
                          Math.floor(point.y / cell);
                var previous = visible.get(key);
                if (!previous || Math.abs(row[2]) > Math.abs(previous.delta)) {
                    visible.set(key, {x: point.x, y: point.y, delta: row[2]});
                }
            });
            visible.forEach(function(item) {
                paintArrow(ctx, item.x, item.y, item.delta,
                           Math.abs(item.delta) / maximum, scale);
            });
        }
        function sync() {
            var scale = scaleForZoom();
            var colored = map.hasLayer(filled);
            syncPolygon(states, scale === "state", "state", colored);
            syncPolygon(cities, scale !== "state", "city",
                        colored && scale === "city");
            syncPolygon(zones, scale === "zone", "zone", colored);
            redraw();
        }
        map.on("overlayadd", function(event) {
            if (event.layer === filled && map.hasLayer(outlines)) {
                map.removeLayer(outlines);
            } else if (event.layer === outlines && map.hasLayer(filled)) {
                map.removeLayer(filled);
            }
            sync();
        });
        map.on("overlayremove", sync);
        map.on("zoomend moveend resize", sync);
        sync();
    })({{ this._parent.get_name() }},
       {{ this.outlines.get_name() }}, {{ this.filled.get_name() }},
       {{ this.states.get_name() }}, {{ this.municipal.get_name() }},
       {% if this.zones %}{{ this.zones.get_name() }}{% else %}null{% endif %},
       {{ this.arrow_data_json }}, {{ this.low }}, {{ this.high }});
    {% endmacro %}
    """)

    def __init__(
        self, outlines: folium.FeatureGroup, filled: folium.FeatureGroup,
        states: folium.GeoJson, municipal: folium.GeoJson,
        zones: folium.GeoJson | None, arrow_data: dict,
    ) -> None:
        super().__init__()
        self._name = "DeltaZoomLayers"
        self.outlines = outlines
        self.filled = filled
        self.states = states
        self.municipal = municipal
        self.zones = zones
        self.arrow_data_json = json.dumps(arrow_data, separators=(",", ":"))
        self.low = STATE_MAX_ZOOM
        self.high = ZONE_MIN_ZOOM


def _display_int(value: object, *, sign: bool = False) -> str:
    if value is None:
        return "—"
    value = int(value)
    return f"{value:+,}" if sign else f"{value:,}"


def _vote_properties(vote: dict | None, *, approx_zone: bool) -> dict:
    if vote is None:
        return dict(regiao="Sem dados comparáveis", delta="—", saldo1="—",
                    saldo2="—", lula="—", flavio="—", virada="—",
                    cor=NO_DATA, com_dados=False)
    delta = int(vote["delta"])
    region = escape(str(vote["municipio"]))
    if approx_zone:
        region += f' · Zona {int(vote["zona"])} (área aproximada)'
    return dict(
        regiao=region, delta=_display_int(delta, sign=True),
        saldo1=_display_int(vote["saldo_1t"], sign=True),
        saldo2=_display_int(vote["saldo_2t"], sign=True),
        lula=_display_int(vote["delta_a"], sign=True),
        flavio=_display_int(vote["delta_b"], sign=True),
        virada=escape(str(vote["virada"])),
        cor=PT_RED if delta > 0 else PL_BLUE if delta < 0 else NEUTRAL,
        com_dados=True,
    )


def _arrow_geometry(
    point, delta: int, maximum: int, bounds: tuple, *,
    size_cap: float = 0.06, size_floor: float = 0.0012, fraction: float = 0.26,
) -> dict:
    """Uma seta geográfica vetorial; sentido é simbólico, não fluxo eleitoral."""
    west, south, east, north = bounds
    span = max(0.0, min(east - west, north - south))
    size = min(size_cap, max(size_floor, span * fraction))
    size *= 0.25 + 0.75 * sqrt(abs(delta) / max(1, maximum))
    direction = -1 if delta > 0 else 1
    x, y = float(point.x), float(point.y)
    tip_x, tip_y = x + direction * size, y + size
    dx, dy = direction / sqrt(2), 1.0 / sqrt(2)
    px, py = -dy, dx
    head, wing = size * 0.48, size * 0.33
    p1 = [tip_x - dx * head + px * wing, tip_y - dy * head + py * wing]
    p2 = [tip_x - dx * head - px * wing, tip_y - dy * head - py * wing]
    return {
        "type": "MultiLineString",
        "coordinates": [
            [[x, y], [tip_x, tip_y]],
            [[tip_x, tip_y], p1],
            [[tip_x, tip_y], p2],
        ],
    }


def _tooltip_style() -> str:
    return ("background:#282a36;color:#f8f8f2;border:1px solid #6272a4;"
            "border-radius:6px;padding:9px;max-width:300px;"
            "white-space:normal;font:12px/1.35 sans-serif;")


def _polygon_tooltip() -> folium.GeoJsonTooltip:
    return folium.GeoJsonTooltip(
        fields=["regiao", "saldo1", "saldo2", "delta", "lula", "flavio", "virada"],
        aliases=["Região", "Saldo 1ºT", "Saldo 2ºT",
                 "Δ saldo", "Δ Lula", "Δ Flávio", "Virada"],
        sticky=False, style=_tooltip_style(),
    )


def _polygons(geo: gpd.GeoDataFrame, *, approx_zone: bool) -> dict:
    geometry_cache = rounded_geometries(geo[["_key", "geometry"]], key="_key")
    features = []
    for key, vote in zip(geo["_key"], geo["_vote"]):
        data = geometry_cache.get(str(key))
        if data is not None:
            features.append({
                "type": "Feature", "geometry": data,
                "properties": _vote_properties(vote, approx_zone=approx_zone),
            })
    return {"type": "FeatureCollection", "features": features}


def _arrow_collection(
    geo: gpd.GeoDataFrame, *, size_cap: float = .06,
    size_floor: float = .0012, fraction: float = .26,
) -> dict:
    values = [v for v in geo["_vote"] if v is not None and int(v["delta"]) != 0]
    maximum = max((abs(int(v["delta"])) for v in values), default=1)
    features = []
    for geometry, vote in zip(geo.geometry, geo["_vote"]):
        if (geometry is None or geometry.is_empty or vote is None
                or not int(vote["delta"])):
            continue
        props = _vote_properties(vote, approx_zone="zona" in vote)
        features.append({
            "type": "Feature",
            "geometry": _arrow_geometry(
                geometry.representative_point(), int(vote["delta"]), maximum,
                geometry.bounds, size_cap=size_cap, size_floor=size_floor,
                fraction=fraction,
            ),
            "properties": {"cor": props["cor"], "regiao": props["regiao"],
                           "delta": props["delta"], "virada": props["virada"]},
        })
    return {"type": "FeatureCollection", "features": features}


def _state_arrows(municipal: gpd.GeoDataFrame, states: list[dict]) -> dict:
    """Uma seta por UF com votos comparáveis; nunca faz union de polígonos."""
    prefix_to_uf = {prefix: uf for uf, prefix in UF_PREFIX.items()}
    geography = defaultdict(list)
    for code, geometry in zip(municipal["_key"], municipal.geometry):
        if geometry is None or geometry.is_empty:
            continue
        uf = prefix_to_uf.get(str(code)[:2])
        if uf:
            geography[uf].append(geometry)
    records = [row for row in states if row["uf"] in geography and int(row["delta"]) != 0]
    maximum = max((abs(int(row["delta"])) for row in records), default=1)
    features = []
    for row in records:
        shapes = geography[row["uf"]]
        # Posição da seta: ponto representativo da cidade mais próxima ao
        # centro do envelope da UF; permanece efetivamente dentro de uma área.
        bounds = [shape.bounds for shape in shapes]
        west = min(b[0] for b in bounds)
        south = min(b[1] for b in bounds)
        east = max(b[2] for b in bounds)
        north = max(b[3] for b in bounds)
        center = ((west + east) / 2, (south + north) / 2)
        points = [shape.representative_point() for shape in shapes]
        point = min(points, key=lambda p: (p.x - center[0])**2 + (p.y - center[1])**2)
        delta = int(row["delta"])
        features.append({
            "type": "Feature",
            "geometry": _arrow_geometry(
                point, delta, maximum, (west, south, east, north),
                size_cap=1.2, size_floor=.22, fraction=.16,
            ),
            "properties": {
                "cor": PT_RED if delta > 0 else PL_BLUE,
                "regiao": f'UF {escape(row["uf"])} · '
                          f'{int(row["municipios_comparaveis"])} municípios comparáveis',
                "delta": _display_int(delta, sign=True),
                "virada": escape(row["virada"]),
            },
        })
    return {"type": "FeatureCollection", "features": features}


def _arrows_group(
    collection: dict, parent: folium.FeatureGroup, *, label: str,
    bounds: list[list[float]],
) -> folium.FeatureGroup | None:
    if not collection["features"]:
        return None
    # 'show=False' materializa as variáveis JS mas não liga nenhuma escala
    # errada durante a inicialização; o controlador de zoom as ativa.
    group = folium.FeatureGroup(name=label, control=False, show=False).add_to(parent)
    BoundedGeoJson(
        collection, bounds=bounds, control=False,
        style_function=lambda f: {
            "color": f["properties"]["cor"], "weight": 2.45, "opacity": .95,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["regiao", "delta", "virada"],
            aliases=["Região", "Δ saldo", "Virada"],
            sticky=False, style=_tooltip_style(),
        ),
    ).add_to(group)
    return group


def delta_map(
    municipal: gpd.GeoDataFrame, *, states: list[dict] | None = None,
    zones: gpd.GeoDataFrame | None = None,
) -> folium.Map:
    """Três escalas automáticas de setas e dois modos exclusivos de visualização.

    0..6: UF (uma seta grande); 7..10: município; >=11: zona se existir malha
    para a UF, senão mantém município. A geometria nunca é inventada.
    """
    if municipal.empty:
        raise ValueError("Não há geometria municipal para desenhar.")
    bounds = leaflet_bounds(municipal)
    west, south, east, north = (float(x) for x in municipal.total_bounds)
    m = atlas_map([(south + north)/2, (west + east)/2])
    outline_mode = folium.FeatureGroup(
        name="Divisões + setas", overlay=True, control=True, show=True,
    ).add_to(m)
    filled_mode = folium.FeatureGroup(
        name="Áreas por delta (sem setas)", overlay=True, control=True, show=False,
    ).add_to(m)
    municipality_layer = BoundedGeoJson(
        _polygons(municipal, approx_zone=False), bounds=bounds, control=False,
        style_function=lambda f: {
            "fillColor": NEUTRAL, "fillOpacity": 0,
            "color": BORDER, "weight": .75,
        },
        tooltip=_polygon_tooltip(),
    ).add_to(m)
    zone_layer = None
    zone_arrows = None
    if zones is not None and not zones.empty:
        zone_bounds = leaflet_bounds(zones)
        zone_layer = BoundedGeoJson(
            _polygons(zones, approx_zone=True), bounds=zone_bounds,
            control=False, show=False,
            style_function=lambda f: {
                "fillColor": NEUTRAL, "fillOpacity": 0,
                "color": BORDER, "weight": .75, "dashArray": "4 2",
            },
            tooltip=_polygon_tooltip(),
        ).add_to(m)
        zone_arrows = _arrows_group(
            _arrow_collection(zones, size_cap=.02, size_floor=.0004, fraction=.28),
            outline_mode, label="Setas zonais", bounds=zone_bounds,
        )
    city_arrows = _arrows_group(
        _arrow_collection(municipal), outline_mode,
        label="Setas municipais", bounds=bounds,
    )
    state_arrows = _arrows_group(
        _state_arrows(municipal, states or []), outline_mode,
        label="Setas estaduais", bounds=bounds,
    )
    m.add_child(DeltaZoomLayers(
        outline_mode, filled_mode, municipality_layer, zone_layer,
        state_arrows, city_arrows, zone_arrows,
    ))
    folium.LayerControl(position="topright", collapsed=False).add_to(m)
    m.fit_bounds(bounds)
    return m
