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

# Escalas do drill-down automatico (como no mapa de apuracao):
# municipios sempre; areas aproximadas de zona a partir de ZONE_ZOOM;
# pontos dos locais de votacao a partir de SITE_ZOOM. A troca e feita no
# navegador (mapa_eleicoes.map_panes); o clique num municipio enquadra a
# cidade inteira (no minimo ZONE_ZOOM se ela tem varias zonas).
ZONE_ZOOM = 10
FOCUS_ZOOM = 11
SITE_ZOOM = 12


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


def zoom_for_bounds(
    bounds: tuple[float, float, float, float],
    *, width: int = 900, height: int = 700,
    min_zoom: int = 4, max_zoom: int = 15,
) -> int:
    """Maior zoom inteiro (Web Mercator) em que (oeste, sul, leste, norte) cabe."""
    west, south, east, north = (float(v) for v in bounds)
    values = (west, south, east, north)
    if not all(math.isfinite(v) for v in values) or west > east or south > north:
        return min_zoom

    def mercator_y(lat: float) -> float:
        lat = max(min(lat, 85.0), -85.0)
        return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))

    lon_fraction = max((east - west) / 360.0, 1e-9)
    lat_fraction = max((mercator_y(north) - mercator_y(south)) / (2 * math.pi), 1e-9)
    zoom = min(math.log2(width / 256 / lon_fraction),
               math.log2(height / 256 / lat_fraction))
    return int(max(min_zoom, min(max_zoom, math.floor(zoom))))
