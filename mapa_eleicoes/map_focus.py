"""Foco na cidade como no mapa de apuracao: a cidade acende, o resto apaga.

Tudo no navegador, sem rerun:
- clique num municipio: enquadra a cidade e a destaca (contorno branco);
- zoom: quando a cidade sob o centro do mapa ocupa a tela (zoom em que ela
  cabe, limitado a ZONE_ZOOM), ela vira o foco; ao arrastar, o foco segue
  a cidade do centro;
- afastar alem do zoom da cidade devolve as cores a todos os municipios.

As demais cidades ficam no cinza escuro do g1. O estilo e aplicado pela
funcao de estilo da propria camada, entao o `resetStyle` do hover do folium
mantem o apagado.
"""
from __future__ import annotations

import json

import folium
from branca.element import MacroElement
from jinja2 import Template

from mapa_eleicoes.map_navigation import ZONE_ZOOM

# Cinza das areas fora de foco e borda escura (amostrados do g1).
DIM_STYLE = {"fillColor": "#23221f", "fillOpacity": 1.0, "color": "#0f1010", "weight": 0.4}
FOCUS_STYLE = {"color": "#ffffff", "weight": 2.6, "fillOpacity": 0.95}


class CityFocus(MacroElement):
    """Liga o foco de cidade a uma camada GeoJson com `map_id` por feicao."""

    _template = Template("""
        {% macro script(this, kwargs) %}
        (function (map, layer) {
            var DIM = {{ this.dim_json }}, FOCUS = {{ this.focus_json }};
            var AUTO_ZOOM = {{ this.auto_zoom }};
            var base = layer.options.style;
            var focus = null, afterClick = false;

            function idOf(l) { return l.feature && l.feature.properties.map_id; }
            function styleFor(feature) {
                var s = Object.assign({}, base ? base(feature) : {});
                if (focus === null) { return s; }
                return Object.assign(s, feature.properties.map_id === focus ? FOCUS : DIM);
            }
            layer.options.style = styleFor;

            function apply() {
                layer.eachLayer(function (l) {
                    layer.resetStyle(l);
                    if (focus !== null && idOf(l) === focus && l.bringToFront) { l.bringToFront(); }
                });
            }
            function rings(latlngs, out) {
                if (latlngs.length && latlngs[0].lat !== undefined) { out.push(latlngs); }
                else { latlngs.forEach(function (part) { rings(part, out); }); }
                return out;
            }
            function contains(l, p) {
                if (!l.getBounds || !l.getBounds().contains(p)) { return false; }
                var inside = false;
                rings(l.getLatLngs(), []).forEach(function (ring) {
                    for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
                        var a = ring[i], b = ring[j];
                        if ((a.lat > p.lat) !== (b.lat > p.lat) &&
                            p.lng < (b.lng - a.lng) * (p.lat - a.lat) / (b.lat - a.lat) + a.lng) {
                            inside = !inside;
                        }
                    }
                });
                return inside;
            }
            function cityAt(p) {
                var found = null;
                layer.eachLayer(function (l) { if (found === null && contains(l, p)) { found = l; } });
                return found;
            }
            function find(id) {
                var found = null;
                layer.eachLayer(function (l) { if (idOf(l) === id) { found = l; } });
                return found;
            }
            // Zoom em que a cidade cabe na tela, limitado ao zoom das zonas.
            function cityZoom(l) { return Math.min(map.getBoundsZoom(l.getBounds()), AUTO_ZOOM); }

            function setFocus(id) {
                if (id === focus) { return; }
                focus = id;
                apply();
            }
            layer.on("click", function (e) {
                if (!idOf(e.layer)) { return; }
                setFocus(idOf(e.layer));
                // O centro do enquadramento pode cair fora de cidade concava:
                // o primeiro moveend (o do proprio enquadramento) nao troca o foco.
                afterClick = true;
                map.fitBounds(e.layer.getBounds(), {padding: [24, 24]});
            });
            map.on("moveend", function () {
                if (afterClick) { afterClick = false; return; }
                var zoom = map.getZoom();
                if (focus !== null) {
                    var current = find(focus);
                    if (!current || zoom < cityZoom(current) - 1) { setFocus(null); }
                }
                var under = cityAt(map.getCenter());
                if (under && zoom >= cityZoom(under)) { setFocus(idOf(under)); }
            });
        })({{ this._parent.get_name() }}, {{ this.layer.get_name() }});
        {% endmacro %}
    """)

    def __init__(self, layer: folium.GeoJson, *, auto_zoom: int = ZONE_ZOOM):
        super().__init__()
        self._name = "CityFocus"
        self.layer = layer
        self.auto_zoom = int(auto_zoom)
        self.dim_json = json.dumps(DIM_STYLE)
        self.focus_json = json.dumps(FOCUS_STYLE)


def context_layer(geometry_json: dict) -> folium.GeoJson:
    """Municipios fora do recorte (mesma UF), no cinza apagado e sem hover."""
    return folium.GeoJson(
        geometry_json,
        name="Contexto",
        style_function=lambda _: dict(DIM_STYLE),
        interactive=False,
        control=False,
    )
