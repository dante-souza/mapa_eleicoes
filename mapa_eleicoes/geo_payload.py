"""GeoJSON enxuto para o mapa: menos bytes e menos trabalho por rerun.

Medido com 5.570 municipios sinteticos (~10 MB de GeoJSON), cada rerun
gastava ~8 s; os maiores custos eram:

- uniao de todos os poligonos so para achar um ponto central (~3 s);
- GeoDataFrame -> JSON a cada execucao (~0,8 s), com 15 casas decimais;
- folium recalculando os limites varrendo todas as coordenadas (~1,2 s).

Aqui a geometria vira dicionarios GeoJSON UMA vez (cache do app), com
coordenadas arredondadas (4 casas ~ 11 m; a malha ja e simplificada a 1 km),
e a camada informa seus limites ja conhecidos.
"""
from __future__ import annotations

import json

import folium
import geopandas as gpd
import numpy as np
import shapely

DECIMALS = 4  # ~11 m no equador; a malha municipal ja e simplificada a 1 km


def rounded_geometries(
    frame: gpd.GeoDataFrame, key: str = "map_id", decimals: int = DECIMALS,
) -> dict[str, dict]:
    """{chave: geometria GeoJSON} com coordenadas arredondadas.

    Arredonda no vetor de coordenadas (sem refazer topologia) e serializa
    pelo GEOS; repete a chave so uma vez (a primeira).
    """
    if frame.empty:
        return {}
    geoms = shapely.transform(
        np.asarray(frame.geometry.values), lambda xy: np.round(xy, decimals)
    )
    out: dict[str, dict] = {}
    for code, text in zip(frame[key], shapely.to_geojson(geoms)):
        if text is None:
            continue
        out.setdefault(str(code), json.loads(text))
    return out


def feature_collection(
    keys: list[str], geometries: dict[str, dict], properties: dict[str, list],
) -> dict:
    """FeatureCollection com as geometrias em cache e as propriedades da vez."""
    names = list(properties)
    columns = [properties[name] for name in names]
    features = []
    for index, code in enumerate(keys):
        geometry = geometries.get(str(code))
        if geometry is None:
            continue
        features.append({
            "type": "Feature",
            "properties": {name: column[index] for name, column in zip(names, columns)},
            "geometry": geometry,
        })
    return {"type": "FeatureCollection", "features": features}


class BoundedGeoJson(folium.GeoJson):
    """GeoJson com limites ja calculados.

    O folium (e o streamlit-folium, para o valor padrao de `bounds`) varre
    todas as coordenadas para descobrir os limites a cada renderizacao.
    """

    def __init__(self, data, *, bounds: list[list[float]], **kwargs):
        super().__init__(data, **kwargs)
        self._known_bounds = bounds

    def _get_self_bounds(self):
        return self._known_bounds


def leaflet_bounds(frame: gpd.GeoDataFrame) -> list[list[float]]:
    """[[sul, oeste], [norte, leste]] a partir das caixas (sem uniao)."""
    west, south, east, north = (float(v) for v in frame.total_bounds)
    return [[south, west], [north, east]]
