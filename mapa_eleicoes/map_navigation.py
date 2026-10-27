"""Navegacao cartografica: zoom/click/drill-down sem depender dos selects.

O hover dos municipios e executado no proprio Leaflet (tooltip), para nao
reiniciar o Streamlit em cada movimento do mouse. Quando o centro do mapa
chega a uma cidade em zoom urbano, mostramos locais TSE oficiais. Clique em
municipio pode focar diretamente sem inventar geometria de secao.
"""
from __future__ import annotations

import math

import geopandas as gpd
from shapely.geometry import Point, box

from mapa_eleicoes.cli import IBGE_UF_BY_PREFIX

# Escalas do drill-down automatico (como no mapa de apuracao):
# municipios sempre; areas aproximadas de zona a partir de ZONE_ZOOM;
# pontos dos locais de votacao a partir de SITE_ZOOM. O clique num
# municipio aproxima ate FOCUS_ZOOM, que ja revela as zonas da cidade.
ZONE_ZOOM = 10
FOCUS_ZOOM = 11
SITE_ZOOM = 12
MAX_CITIES_IN_VIEW = 80


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


def should_render_zones(zoom: object, available: bool) -> bool:
    try:
        z = float(zoom)
    except (TypeError, ValueError):
        return False
    return bool(available and math.isfinite(z) and z >= ZONE_ZOOM)


def valid_bounds(bounds: dict | None) -> tuple[float, float, float, float] | None:
    """Bounds do Leaflet ({_southWest, _northEast}) -> (oeste, sul, leste, norte)."""
    if not isinstance(bounds, dict):
        return None
    south_west = valid_position(bounds.get("_southWest"))
    north_east = valid_position(bounds.get("_northEast"))
    if south_west is None or north_east is None:
        return None
    (south, west), (north, east) = south_west, north_east
    if south > north or west > east:
        return None
    return west, south, east, north


def municipalities_in_view(
    geometries: gpd.GeoDataFrame,
    bounds: dict | None,
    center: dict | None = None,
    *,
    limit: int = MAX_CITIES_IN_VIEW,
) -> list[str]:
    """Municipios (IBGE) que tocam a area visivel; centro primeiro.

    Sem bounds validos, cai para o municipio sob o centro. Limite evita
    carregar dezenas de cidades numa vista ampla.
    """
    if "map_id" not in geometries.columns:
        return []
    first = municipality_at(geometries, center)
    box_bounds = valid_bounds(bounds)
    if box_bounds is None:
        return [first] if first else []
    window = box(*box_bounds)
    try:
        indices = geometries.sindex.query(window, predicate="intersects")
        codes = [str(geometries.iloc[int(i)]["map_id"]) for i in indices]
    except (AttributeError, TypeError):
        codes = [
            str(code) for code, shape in zip(geometries["map_id"], geometries.geometry)
            if shape is not None and shape.intersects(window)
        ]
    ordered = ([first] if first else []) + sorted(set(codes) - {first})
    return ordered[:limit]
