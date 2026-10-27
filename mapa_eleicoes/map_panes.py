"""Camadas que aparecem/somem por zoom INTEIRAMENTE no navegador.

O mapa de apuracao troca municipio -> zona -> local conforme o zoom, sem
recarregar a pagina. Aqui isso e feito com panes do Leaflet: cada camada de
detalhe vive num pane proprio e um handler de `zoomend` mostra ou esconde o
pane. Nenhum zoom/pan volta ao Streamlit, entao nao ha rerun, overlay cinza
nem reset da camera.

Detalhes que importam:
- o mapa usa `prefer_canvas`; um canvas por pane bloquearia o hover das
  camadas de baixo. Os panes de detalhe usam SVG e o <svg> do pane ignora o
  ponteiro: so os poligonos/pontos capturam o mouse;
- os panes sao criados ANTES das camadas que os usam (adicione este
  elemento ao mapa antes delas).
"""
from __future__ import annotations

import json

from branca.element import MacroElement
from folium.elements import JSCSSMixin
from folium.plugins import MarkerCluster
from jinja2 import Template

from mapa_eleicoes.map_navigation import SITE_ZOOM, ZONE_ZOOM

# nome do pane -> z-index (overlayPane do Leaflet = 400; marcadores = 600)
DISTRICT_PANE = "atlasZonasUF"
ZONE_PANE = "atlasZonasCidade"
SITE_PANE = "atlasLocais"
PANE_Z = {DISTRICT_PANE: 405, ZONE_PANE: 410, SITE_PANE: 420}


class ZoomPanes(MacroElement):
    """Cria os panes de detalhe e liga/desliga cada um pelo zoom do mapa.

    `min_zoom` = None deixa o pane sempre visivel (modo explicito).
    """

    _template = Template("""
        {% macro header(this, kwargs) %}
        <style>
          .leaflet-pane.atlas-detail-pane > svg { pointer-events: none; }
        </style>
        {% endmacro %}
        {% macro script(this, kwargs) %}
        (function (map) {
            var specs = {{ this.specs_json }};
            map._paneRenderers = map._paneRenderers || {};
            specs.forEach(function (spec) {
                var pane = map.getPane(spec.name) || map.createPane(spec.name);
                pane.style.zIndex = spec.z;
                pane.classList.add("atlas-detail-pane");
                if (!map._paneRenderers[spec.name]) {
                    map._paneRenderers[spec.name] = L.svg({pane: spec.name});
                }
            });
            function sync() {
                var zoom = map.getZoom();
                specs.forEach(function (spec) {
                    if (spec.min === null) { return; }
                    map.getPane(spec.name).style.display = zoom >= spec.min ? "" : "none";
                });
            }
            map.on("zoomend", sync);
            sync();
        })({{ this._parent.get_name() }});
        {% endmacro %}
    """)

    def __init__(self, gates: dict[str, int | None]):
        super().__init__()
        self._name = "ZoomPanes"
        unknown = set(gates) - set(PANE_Z)
        if unknown:
            raise ValueError(f"Pane desconhecido: {sorted(unknown)}")
        self.specs = [
            {"name": name, "z": PANE_Z[name], "min": gates[name]}
            for name in sorted(gates, key=PANE_Z.get)
        ]
        self.specs_json = json.dumps(self.specs)


def explorer_gates(detail: str) -> dict[str, int | None]:
    """Zoom minimo de cada pane conforme o detalhamento escolhido."""
    if detail == "Seção eleitoral (locais)":
        return {ZONE_PANE: ZONE_ZOOM, SITE_PANE: None}
    if detail == "Zona eleitoral (aproximada)":
        return {DISTRICT_PANE: None, SITE_PANE: SITE_ZOOM}
    return {ZONE_PANE: ZONE_ZOOM, SITE_PANE: SITE_ZOOM}


class ClusterAssets(JSCSSMixin, MacroElement):
    """Carrega o Leaflet.markercluster junto com o mapa base.

    O streamlit-folium so injeta os scripts na montagem do mapa. Os locais
    de votacao chegam depois, numa camada dinamica; sem isto, a camada de
    locais falha com `L.markerClusterGroup is not a function` e a camera
    pedida no mesmo rerun nao e aplicada.
    """

    _template = Template("")
    default_js = MarkerCluster.default_js
    default_css = MarkerCluster.default_css

    def __init__(self):
        super().__init__()
        self._name = "ClusterAssets"
