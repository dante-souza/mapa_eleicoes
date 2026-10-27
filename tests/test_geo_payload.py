"""GeoJSON enxuto: geometria em cache, coordenadas arredondadas, limites prontos."""
from __future__ import annotations

import json

import folium
import geopandas as gpd
from shapely.geometry import Polygon

from mapa_eleicoes.geo_payload import (
    BoundedGeoJson, feature_collection, leaflet_bounds, rounded_geometries,
)


def frame():
    return gpd.GeoDataFrame(
        {"map_id": ["3550308", "3304557"]},
        geometry=[
            Polygon([(-46.633308123456, -23.55052), (-46.5, -23.5), (-46.6, -23.4)]),
            Polygon([(-43.2, -22.9), (-43.1, -22.9), (-43.15, -22.8)]),
        ],
        crs="EPSG:4326",
    )


def test_coordinates_rounded_to_four_decimals():
    geoms = rounded_geometries(frame())
    first = geoms["3550308"]["coordinates"][0][0]
    assert first == [-46.6333, -23.5505]
    # 15 casas decimais nao chegam ao navegador
    assert "633308" not in json.dumps(geoms)


def test_feature_collection_joins_cached_geometry_and_properties():
    geoms = rounded_geometries(frame())
    fc = feature_collection(["3304557", "9999999"], geoms,
                            {"map_id": ["3304557", "9999999"], "primeiro": ["A", "B"]})
    assert [f["properties"]["primeiro"] for f in fc["features"]] == ["A"]
    assert fc["features"][0]["geometry"] is geoms["3304557"]


def test_bounded_geojson_skips_coordinate_scan():
    bounds = leaflet_bounds(frame())
    assert bounds == [[-23.55052, -46.633308123456], [-22.8, -43.1]]
    fmap = folium.Map()
    layer = BoundedGeoJson(feature_collection(["3550308"], rounded_geometries(frame()),
                                              {"map_id": ["3550308"]}), bounds=bounds).add_to(fmap)
    assert layer.get_bounds() == bounds
    assert fmap.get_bounds() == bounds
