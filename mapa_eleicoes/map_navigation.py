"""Navegacao cartografica: zoom/click/drill-down sem depender dos selects.

O hover dos municipios e executado no proprio Leaflet (tooltip), para nao
reiniciar o Streamlit em cada movimento do mouse. Quando o centro do mapa
chega a uma cidade em zoom urbano, mostramos locais TSE oficiais. Clique em
municipio pode focar diretamente sem inventar geometria de secao.
"""
from __future__ import annotations

import math

import geopandas as gpd
from shapely.geometry import Point

from mapa_eleicoes.cli import IBGE_UF_BY_PREFIX

SITE_ZOOM = 10
FOCUS_ZOOM = 11


def valid_position(position: dict | None) -> tuple[float, float] | None:
    if not isinstance(position, dict):
        return None
    try:
        lat = float(position["lat"])
        lng = float(position["lng"])
    except (TypeError, ValueError, KeyError):
        return None
    if not math.isfinite(lat) or not math.isfinite(lng):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat, lng


def municipality_at(
    geometries: gpd.GeoDataFrame,
    position: dict | None,
) -> str | None:
    """Resolve o poligono real do IBGE sob o clique/centro do mapa."""
    point_tuple = valid_position(position)
    if point_tuple is None or "map_id" not in geometries.columns:
        return None
    lat, lng = point_tuple
    point = Point(lng, lat)
    try:
        # Busca espacial: custo proporcional a poucos poligonos proximos.
        candidates = geometries.sindex.query(point, predicate="intersects")
        for idx in candidates:
            feature = geometries.iloc[int(idx)]
            if feature.geometry is not None and feature.geometry.covers(point):
                return str(feature["map_id"])
    except (AttributeError, TypeError):
        # Recuperacao para GeoPandas sem indice espacial.
        for _, feature in geometries.iterrows():
            if feature.geometry is not None and feature.geometry.covers(point):
                return str(feature["map_id"])
    return None


def should_render_sites(zoom: object, available: bool) -> bool:
    try:
        z = float(zoom)
    except (TypeError, ValueError):
        return False
    return bool(available and math.isfinite(z) and z >= SITE_ZOOM)


def state_for_municipality(code_ibge: str | None) -> str | None:
    if not isinstance(code_ibge, str) or len(code_ibge) != 7 or not code_ibge.isdigit():
        return None
    return IBGE_UF_BY_PREFIX.get(code_ibge[:2])


def focus_for_view(
    geometry: gpd.GeoDataFrame,
    view: dict,
    *,
    allow_click: bool = True,
) -> str | None:
    """Clique anterior tem prioridade; senao, centro do viewport em zoom urbano."""
    if allow_click and view.get("clicked_ibge"):
        return view["clicked_ibge"]
    if should_render_sites(view.get("zoom"), True):
        return municipality_at(geometry, view.get("center"))
    return None
