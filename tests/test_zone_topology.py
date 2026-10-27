"""Regressao GEOS side location conflict durante uniao dos setores IBGE.

Nao toca app.py, paletas, navegacao ou pipeline de votos. Malhas
invalidas sao reparadas na ENTRADA do dissolve, preservando atributos.
"""
from __future__ import annotations

import geopandas as gpd
import polars as pl
import pytest
import shapely
from shapely.geometry import Polygon, box

from mapa_eleicoes import zone_geometry as zg


def fixture_tracts():
    # Auto-intersecao tipo laço ("bow-tie"): GEOS pode falhar no dissolve.
    invalid = Polygon([
        (0, 0), (2, 2), (0, 2), (2, 0), (0, 0)
    ])
    assert not invalid.is_valid
    return gpd.GeoDataFrame(
        {
            "cd_setor": ["330455700000001", "330455700000002"],
            "codigo_ibge": ["3304557", "3304557"],
            "geometry": [invalid, box(3, 0, 5, 2)],
        },
        crs=zg.METRIC_CRS,
    )


def fixture_assignments():
    return pl.DataFrame([
        {
            "cd_setor": "330455700000001",
            "codigo_ibge": "3304557",
            "uf": "RJ",
            "cd_municipio_tse": "60011",
            "zona": 1,
            "criterio": "locais",
        },
        {
            "cd_setor": "330455700000002",
            "codigo_ibge": "3304557",
            "uf": "RJ",
            "cd_municipio_tse": "60011",
            "zona": 1,
            "criterio": "proximidade",
        },
    ])


def test_repair_preserves_tracts_and_does_not_mutate_original():
    raw = fixture_tracts()
    clean = zg._repair_tracts_for_union(raw)
    assert clean.geometry.is_valid.all()
    assert len(clean) == len(raw)
    assert clean["cd_setor"].to_list() == raw["cd_setor"].to_list()
    assert not raw.geometry.is_valid.all()
    assert clean.geometry.area.min() > 0


def test_zones_dissolve_repairs_invalid_input_before_union():
    zones = zg.dissolve_zones(
        fixture_tracts(), fixture_assignments(), simplify_meters=0
    )
    assert len(zones) == 1
    assert zones["n_setores"].to_list() == [2]
    assert zones["setores_por_proximidade"].to_list() == [1]
    assert zones.geometry.is_valid.all()
    assert zones["map_id"].to_list() == ["RJ:60011:1"]
    assert zones["aproximada"].to_list() == [True]


def test_districts_dissolve_repairs_invalid_input_before_union():
    districts = zg.dissolve_districts(
        fixture_tracts(), fixture_assignments(), simplify_meters=0
    )
    assert len(districts) == 1
    assert districts.geometry.is_valid.all()
    assert districts["n_setores"].to_list() == [2]
    assert districts["map_id"].to_list() == ["RJ:1"]


def test_precision_retry_only_when_geos_raises(monkeypatch):
    original = gpd.GeoDataFrame.dissolve
    calls = []

    def fail_once(frame, *args, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            raise shapely.errors.GEOSException(
                "TopologyException: side location conflict"
            )
        return original(frame, *args, **kwargs)

    monkeypatch.setattr(gpd.GeoDataFrame, "dissolve", fail_once)
    zones = zg.dissolve_zones(
        fixture_tracts(), fixture_assignments(), simplify_meters=0
    )
    assert len(calls) == 2
    assert zones["n_setores"].to_list() == [2]
    assert zones.geometry.is_valid.all()


def test_non_polygonal_repair_fails_instead_of_dropping_sector(monkeypatch):
    # Testa contrato de seguranca: uma entrada que perdeu area apos
    # repair deve falhar, nao gerar "zona" com votos de setor descartado.
    tracts = fixture_tracts()
    original = shapely.make_valid

    def no_polygon(geometry):
        return shapely.geometry.LineString([(0, 0), (1, 1)])

    monkeypatch.setattr(shapely, "make_valid", no_polygon)
    with pytest.raises(ValueError, match="nao possui area poligonal"):
        zg._repair_tracts_for_union(tracts)


def test_makefile_supports_uf_alias_without_ever_editing_map_sources():
    from pathlib import Path
    makefile = Path(__file__).resolve().parents[1] / "Makefile"
    text = makefile.read_text(encoding="utf-8")
    assert "ZONE_TARGET_UFS = $(if $(strip $(ZONE_UFS))" in text
    assert '$(if $(ZONE_TARGET_UFS),--ufs "$(ZONE_TARGET_UFS)",)' in text
