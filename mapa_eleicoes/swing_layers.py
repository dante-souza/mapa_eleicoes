"""Camadas de deltas no Folium, separadas da apuração existente.

Dois controles visuais alternáveis no próprio Leaflet (sem rerun Streamlit):
- limites transparentes + setas esquemáticas;
- regiões preenchidas pelo sinal do delta, sem setas.

Os polígonos são carregados uma única vez. As setas são um GeoJSON vetorial.
"""
from __future__ import annotations

from html import escape
from math import sqrt

import folium
import geopandas as gpd
from branca.element import MacroElement
from jinja2 import Template

from mapa_eleicoes.geo_payload import BoundedGeoJson, leaflet_bounds, rounded_geometries
from mapa_eleicoes.map_tiles import atlas_map
from mapa_eleicoes.party_colors import PL_BLUE, PT_RED

NEUTRAL = "#6272a4"
BORDER = "#a6a6b5"
NO_DATA = "#44475a"


class ExclusiveDeltaOverlays(MacroElement):
    """Dois modos visuais com uma única geometria municipal/zonal carregada.

    Polígonos permanecem no mapa; o controle muda apenas o estilo e a
    visibilidade do GeoJSON vetorial de setas, sem rerun nem tiles adicionais.
    """

    _template = Template("""
    {% macro script(this, kwargs) %}
    (function(map, outlineGroup, filledGroup, polygons) {
        function outlineStyle(feature) {
            return {fillColor: "#6272a4", fillOpacity: 0,
                    color: "#a6a6b5", weight: 0.8};
        }
        function filledStyle(feature) {
            return {fillColor: feature.properties.cor,
                    fillOpacity: feature.properties.com_dados ? 0.72 : 0,
                    color: "#161717", weight: 0.5};
        }
        map.on("overlayadd", function(event) {
            if (event.layer === filledGroup) {
                if (map.hasLayer(outlineGroup)) { map.removeLayer(outlineGroup); }
                polygons.setStyle(filledStyle);
            } else if (event.layer === outlineGroup) {
                if (map.hasLayer(filledGroup)) { map.removeLayer(filledGroup); }
                polygons.setStyle(outlineStyle);
            }
        });
        map.on("overlayremove", function(event) {
            if (event.layer === filledGroup && !map.hasLayer(outlineGroup)) {
                polygons.setStyle(outlineStyle);
            }
        });
    })({{ this._parent.get_name() }}, {{ this.outlines.get_name() }},
       {{ this.filled.get_name() }}, {{ this.polygons.get_name() }});
    {% endmacro %}
    """)

    def __init__(
        self, outlines: folium.FeatureGroup, filled: folium.FeatureGroup,
        polygons: folium.GeoJson,
    ):
        super().__init__()
        self._name = "ExclusiveDeltaOverlays"
        self.outlines = outlines
        self.filled = filled
        self.polygons = polygons


def _display_int(value: object, *, sign: bool = False) -> str:
    if value is None:
        return "—"
    number = int(value)
    return f"{number:+,}" if sign else f"{number:,}"


def _vote_properties(vote: dict | None, *, approx_zone: bool) -> dict[str, str]:
    if vote is None:
        return {
            "regiao": "Sem dados comparáveis", "delta": "—",
            "saldo1": "—", "saldo2": "—", "lula": "—",
            "flavio": "—", "virada": "—", "cor": NO_DATA,
            "com_dados": False,
        }
    delta = int(vote["delta"])
    name = escape(str(vote["municipio"]))
    if approx_zone:
        name += f' · Zona {int(vote["zona"])} (área aproximada)'
    return {
        "regiao": name,
        "delta": _display_int(delta, sign=True),
        "saldo1": _display_int(vote["saldo_1t"], sign=True),
        "saldo2": _display_int(vote["saldo_2t"], sign=True),
        "lula": _display_int(vote["delta_a"], sign=True),
        "flavio": _display_int(vote["delta_b"], sign=True),
        "virada": escape(str(vote["virada"])),
        "cor": PT_RED if delta > 0 else PL_BLUE if delta < 0 else NEUTRAL,
        "com_dados": True,
    }


def _arrow_geometry(point, delta: int, maximum: int, bounds: tuple) -> dict:
    """Desenha haste + duas pontas como UMA MultiLineString.

    Direção é simbólica (esquerda/direita), NÃO deslocamento geográfico;
    tamanho relativo a |delta| e limitado ao tamanho da região.
    """
    west, south, east, north = bounds
    span = max(0.0, min(east - west, north - south))
    size = min(0.06, max(0.0012, span * 0.26))
    size *= 0.25 + 0.75 * sqrt(abs(delta) / max(1, maximum))
    direction = -1 if delta > 0 else 1
    x, y = float(point.x), float(point.y)
    tip_x, tip_y = x + direction * size, y + size
    # Ponta triangular aberta, orientada na direção da haste.
    dx, dy = direction / sqrt(2), 1.0 / sqrt(2)
    px, py = -dy, dx
    head = size * 0.48
    wing = size * 0.33
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


def delta_map(geo: gpd.GeoDataFrame, *, approx_zone: bool = False) -> folium.Map:
    """Constrói dois overlays; o primeiro começa ativo e o outro desligado.

    geo tem geometry e _vote (dicionário de swing_results ou None).
    Geometrias sem voto continuam como contornos, mas não ganham delta
    artificial. O tile-base nunca é escondido pelo seletor de camadas.
    """
    if geo.empty:
        raise ValueError("Não há geometria para desenhar.")
    bounds = leaflet_bounds(geo)
    west, south, east, north = map(float, geo.total_bounds)
    map_view = atlas_map([(south + north) / 2, (west + east) / 2])
    maximum = max((abs(int(v["delta"])) for v in geo["_vote"] if v is not None), default=1) or 1

    # Serializa coordenadas com 4 casas como no mapa principal: evita duplicar
    # MB de GeoJSON com 15 casas decimais para ~5.570 municípios.
    geometries = rounded_geometries(geo[["_key", "geometry"]], key="_key")
    polygons = []
    arrows = []
    for key, geometry, vote in zip(geo["_key"], geo.geometry, geo["_vote"]):
        if geometry is None or geometry.is_empty or str(key) not in geometries:
            continue
        props = _vote_properties(vote, approx_zone=approx_zone)
        polygons.append({
            "type": "Feature",
            "geometry": geometries[str(key)],
            "properties": props,
        })
        if vote is not None and int(vote["delta"]) != 0:
            point = geometry.representative_point()
            arrows.append({
                "type": "Feature",
                "geometry": _arrow_geometry(point, int(vote["delta"]), maximum, geometry.bounds),
                "properties": {
                    "cor": props["cor"],
                    "regiao": props["regiao"],
                    "delta": props["delta"],
                },
            })

    polygon_collection = {"type": "FeatureCollection", "features": polygons}
    tooltip_style = (
        "background:#282a36;color:#f8f8f2;border:1px solid #6272a4;"
        "border-radius:6px;padding:9px;max-width:310px;"
        "white-space:normal;font:12px/1.35 sans-serif;"
    )

    def tooltip():
        return folium.GeoJsonTooltip(
            fields=["regiao", "saldo1", "saldo2", "delta", "lula", "flavio", "virada"],
            aliases=["Região", "Saldo 1ºT", "Saldo 2ºT", "Δ saldo",
                     "Δ Lula", "Δ Flávio", "Virada"],
            sticky=False, style=tooltip_style,
        )

    outline_group = folium.FeatureGroup(
        name="Divisões + setas", overlay=True, control=True, show=True,
    )
    filled_group = folium.FeatureGroup(
        name="Áreas por delta (sem setas)", overlay=True, control=True, show=False,
    )
    # Uma única camada geográfica base, com contornos; o JS troca seu estilo
    # ao ligar a segunda opção. Assim não duplicamos milhares de polígonos.
    polygon_layer = BoundedGeoJson(
        polygon_collection, bounds=bounds, control=False,
        style_function=lambda f: {
            "fillColor": NEUTRAL, "fillOpacity": 0,
            "color": BORDER, "weight": 0.8,
        },
        tooltip=tooltip(),
    ).add_to(map_view)

    if arrows:
        BoundedGeoJson(
            {"type": "FeatureCollection", "features": arrows}, bounds=bounds,
            style_function=lambda f: {
                "color": f["properties"]["cor"], "weight": 2.3,
                "opacity": 0.95, "fillOpacity": 0,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["regiao", "delta"], aliases=["Região", "Δ saldo"],
                sticky=False, style=tooltip_style,
            ),
        ).add_to(outline_group)

    outline_group.add_to(map_view)
    filled_group.add_to(map_view)
    map_view.add_child(ExclusiveDeltaOverlays(outline_group, filled_group, polygon_layer))
    folium.LayerControl(position="topright", collapsed=False).add_to(map_view)
    map_view.fit_bounds(bounds)
    return map_view
