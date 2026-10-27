"""Foco na cidade como no mapa de apuracao: a cidade acende, o resto apaga.

Tudo no navegador, sem rerun:
- clique num municipio: enquadra a cidade e a destaca (contorno branco);
- zoom: quando a cidade sob o centro do mapa ocupa a tela (zoom em que ela
  cabe, limitado a ZONE_ZOOM), ela vira o foco; ao arrastar, o foco segue
  a cidade do centro;
- afastar alem do zoom da cidade, o botao "Voltar" no mapa ou a tecla Esc
  devolvem as cores a todos os municipios (o botao tambem volta ao
  enquadramento inicial).

Com foco, as demais cidades ficam quase pretas e o mapa de fundo escurece
(classe `atlas-focus` no container), para a cidade saltar aos olhos. O estilo e aplicado pela
funcao de estilo da propria camada, entao o `resetStyle` do hover do folium
mantem o apagado.
"""
from __future__ import annotations

import json

import folium
from branca.element import MacroElement
from jinja2 import Template

from mapa_eleicoes.geo_payload import BoundedGeoJson
from mapa_eleicoes.map_navigation import ZONE_ZOOM

# Fora de foco: quase preto semi-transparente, some no tile escurecido.
DIM_STYLE = {"fillColor": "#0e0e0f", "fillOpacity": 0.82, "color": "#1a1a1d", "weight": 0.3}
FOCUS_STYLE = {"color": "#ffffff", "weight": 2.8, "fillOpacity": 1.0}

# Fundo (tiles) escurecido enquanto ha foco; botao "Voltar" no estilo do mapa.
FOCUS_CSS = """
<style>
.atlas-focus .leaflet-tile-pane { filter: brightness(.12); transition: filter .25s; }
.leaflet-tile-pane { transition: filter .25s; }
.atlas-back {
  display: none; cursor: pointer; padding: 6px 12px; border-radius: 6px;
  background: rgba(22,23,23,.92); color: #f8f8f2; border: 1px solid #555;
  font: 600 13px sans-serif;
}
.atlas-focus .atlas-back { display: block; }
.atlas-back:hover { background: #2a2a2e; }
</style>
"""


class CityFocus(MacroElement):
    """Liga o foco de cidade a uma camada GeoJson com `map_id` por feicao."""

    _template = Template("""
        {% macro header(this, kwargs) %}{{ this.css }}{% endmacro %}
        {% macro script(this, kwargs) %}
        (function (map, layer) {
            var DIM = {{ this.dim_json }}, FOCUS = {{ this.focus_json }};
            var AUTO_ZOOM = {{ this.auto_zoom }};
            var INITIAL_CITY = {{ this.initial_focus_json }};
            var base = layer.options.style;
            var focus = null, afterClick = false, home = null, before = null;
            // Enquadramento inicial: depois do fit_bounds do proprio script.
            setTimeout(function () { home = map.getBounds(); }, 0);

            var Back = L.Control.extend({
                options: {position: "topright"},
                onAdd: function () {
                    var div = L.DomUtil.create("div", "atlas-back");
                    div.innerHTML = "&#8592; Voltar ao mapa completo";
                    div.title = "Tirar o destaque (Esc)";
                    L.DomEvent.disableClickPropagation(div);
                    L.DomEvent.on(div, "click", function () { reset(true); });
                    return div;
                }
            });
            new Back().addTo(map);

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
                var box = map.getContainer();
                if (focus === null) { L.DomUtil.removeClass(box, "atlas-focus"); }
                else { L.DomUtil.addClass(box, "atlas-focus"); }
                apply();
            }
            // Voltar: sem foco e, pelo botao, de volta ao enquadramento inicial.
            // `suppress` evita que o moveend do proprio retorno reacenda a
            // cidade que estiver no centro.
            var suppress = false;
            function reset(goHome) {
                var target = before || home;
                setFocus(null);
                before = null;
                if (goHome && target) { suppress = true; map.fitBounds(target); }
            }
            document.addEventListener("keydown", function (e) {
                if (e.key === "Escape" && focus !== null) { reset(true); }
            });
            // Vincular o clique à FEIÇÃO, não ao grupo GeoJSON.
            // MouseEvent de um GeoJSON propagado nem sempre fornece e.layer;
            // sourceTarget é a referência moderna, mas o listener direto
            // evita a dependência de ambos e funciona também com Canvas.
            function focusCity(featureLayer) {
                var id = idOf(featureLayer);
                if (!id) { return; }
                if (focus === null) { before = map.getBounds(); }
                setFocus(id);
                // O primeiro moveend é provocado pelo próprio enquadramento.
                afterClick = true;
                map.fitBounds(featureLayer.getBounds(), {padding: [24, 24]});
            }
            layer.eachLayer(function (featureLayer) {
                if (idOf(featureLayer)) {
                    featureLayer.on("click", function () {
                        focusCity(featureLayer);
                    });
                }
            });
            // Fallback: se Canvas/pane impedir a entrega direta do clique
            // ao polígono, resolver a cidade pela coordenada no próprio mapa.
            // Não duplicar quando o clique já passou pelo listener da feição.
            map.on("click", function (e) {
                if (e.sourceTarget && idOf(e.sourceTarget)) { return; }
                var city = e.latlng ? cityAt(e.latlng) : null;
                if (city) { focusCity(city); }
            });

            // st_folium pode redesenhar o componente após um clique para
            // carregar locais de votação. Restaura foco/câmera explicitamente.
            // Deferir até depois do fit_bounds inicial do Folium.
            if (INITIAL_CITY !== null) {
                setTimeout(function () {
                    var previous = find(INITIAL_CITY);
                    if (previous) {
                        home = map.getBounds();
                        before = home;
                        setFocus(INITIAL_CITY);
                        afterClick = true;
                        map.fitBounds(previous.getBounds(), {padding: [24, 24]});
                    }
                }, 0);
            }
            map.on("moveend", function () {
                if (afterClick) { afterClick = false; return; }
                if (suppress) { suppress = false; return; }
                var zoom = map.getZoom();
                if (focus !== null) {
                    var current = find(focus);
                    if (!current || zoom < cityZoom(current) - 1) { setFocus(null); before = null; }
                }
                var under = cityAt(map.getCenter());
                if (under && zoom >= cityZoom(under)) { setFocus(idOf(under)); }
            });
        })({{ this._parent.get_name() }}, {{ this.layer.get_name() }});
        {% endmacro %}
    """)

    def __init__(
        self, layer: folium.GeoJson, *, auto_zoom: int = ZONE_ZOOM,
        initial_focus: str | None = None,
    ):
        super().__init__()
        self._name = "CityFocus"
        self.layer = layer
        self.auto_zoom = int(auto_zoom)
        self.initial_focus_json = json.dumps(initial_focus)
        self.dim_json = json.dumps(DIM_STYLE)
        self.focus_json = json.dumps(FOCUS_STYLE)
        self.css = FOCUS_CSS


class FocusBackdrop(MacroElement):
    """Cidade escolhida no seletor: fundo escurecido desde a carga do mapa."""

    _template = Template("""
        {% macro header(this, kwargs) %}{{ this.css }}{% endmacro %}
        {% macro script(this, kwargs) %}
        L.DomUtil.addClass({{ this._parent.get_name() }}.getContainer(), "atlas-focus");
        {% endmacro %}
    """)

    def __init__(self):
        super().__init__()
        self._name = "FocusBackdrop"
        self.css = FOCUS_CSS


def context_layer(geometry_json: dict, *, bounds: list[list[float]] | None = None) -> folium.GeoJson:
    """Municipios fora do recorte (mesma UF), no cinza apagado e sem hover."""
    if bounds is not None:
        return BoundedGeoJson(
            geometry_json, bounds=bounds, name="Contexto",
            style_function=lambda _: dict(DIM_STYLE), interactive=False, control=False,
        )
    return folium.GeoJson(
        geometry_json,
        name="Contexto",
        style_function=lambda _: dict(DIM_STYLE),
        interactive=False,
        control=False,
    )
