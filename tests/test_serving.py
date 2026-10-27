"""Serve materializado: dados reais agregados, schema estável e cache."""
from __future__ import annotations

import gzip
import json

import polars as pl
import pytest

from mapa_eleicoes import serving


def make_source(root, uf, rows):
    folder = root / "processed" / "2026"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"votos_{uf}.csv.gz"
    with gzip.open(path, "wt", encoding="utf-8") as target:
        pl.DataFrame(rows).write_csv(target)
    return path


def rows(uf="RR"):
    return {
        "ano": [2026, 2026, 2026],
        "turno": [1, 2, 1],
        "uf": [uf] * 3,
        "cd_municipio_tse": ["03010"] * 3,
        "municipio": ["BOA VISTA"] * 3,
        "zona": [1, 1, 1],
        "cargo": ["Governador", "Governador", "Senador"],
        "numero": ["13", "22", "131"],
        "candidato": ["A", "B", "C"],
        "tipo_voto": ["nominal", "nominal", "nominal"],
        "votos": [10, 11, 12],
    }


def test_creates_app_ready_parquet_and_catalog(tmp_path):
    make_source(tmp_path, "RR", rows())
    catalogue = serving.prepare_serving(2026, root=tmp_path)
    target = tmp_path / "serving" / "2026" / "votos_RR.parquet"
    assert target.exists()
    assert catalogue["fontes"]["votos_RR.csv.gz"]["linhas"] == 3
    assert catalogue["geografia"]["municipios"] is False
    assert catalogue["geografia"]["zonas_poligonos"] is False
    values = pl.read_parquet(target)
    assert values.schema["votos"] == pl.Int64
    assert values.schema["zona"] == pl.Int32
    assert values.schema["cd_municipio_tse"] == pl.String
    assert values["cd_municipio_tse"].to_list() == ["03010"] * 3
    assert {(c["cargo"], c["turno"]) for c in catalogue["fontes"]["votos_RR.csv.gz"]["cargos_turnos"]} == {
        ("Governador", 1), ("Governador", 2), ("Senador", 1)
    }


def test_repeatable_cache_does_not_rewrite_parquet(tmp_path):
    make_source(tmp_path, "RR", rows())
    serving.prepare_serving(2026, root=tmp_path)
    target = tmp_path / "serving" / "2026" / "votos_RR.parquet"
    first_mtime = target.stat().st_mtime_ns
    result = serving.prepare_serving(2026, root=tmp_path)
    assert target.stat().st_mtime_ns == first_mtime
    assert result["fontes"]["votos_RR.csv.gz"]["linhas"] == 3


def test_president_second_turn_is_not_fabricated(tmp_path):
    values = rows()
    values["cargo"] = ["Presidente", "Presidente", "Presidente"]
    values["turno"] = [1, 1, 1]
    make_source(tmp_path, "BR", values)
    catalogue = serving.prepare_serving(2026, root=tmp_path)
    items = catalogue["fontes"]["votos_BR.csv.gz"]["cargos_turnos"]
    assert {item["turno"] for item in items} == {1}
    assert not any(item["turno"] == 2 for item in items)


def test_source_removed_cleans_stale_parquet(tmp_path):
    source = make_source(tmp_path, "RR", rows())
    serving.prepare_serving(2026, root=tmp_path)
    source.unlink()
    make_source(tmp_path, "BR", rows("RR"))
    serving.prepare_serving(2026, root=tmp_path)
    assert not (tmp_path / "serving" / "2026" / "votos_RR.parquet").exists()
    assert (tmp_path / "serving" / "2026" / "votos_BR.parquet").exists()


def test_serving_rejects_missing_and_negative_data(tmp_path):
    with pytest.raises(FileNotFoundError, match="Sem resultados"):
        serving.prepare_serving(2026, root=tmp_path)
    values = rows()
    values["votos"] = [10, -1, 12]
    make_source(tmp_path, "RR", values)
    with pytest.raises(ValueError, match="votos negativos"):
        serving.prepare_serving(2026, root=tmp_path)


def test_geo_status_in_catalog_without_fake_zones(tmp_path):
    make_source(tmp_path, "RR", rows())
    geo = tmp_path / "geo"
    geo.mkdir()
    (geo / "municipios.geojson").write_text('{"type":"FeatureCollection","features":[]}')
    reference = tmp_path / "reference"
    reference.mkdir()
    (reference / "tse_ibge.csv").write_text("uf,cd_municipio_tse,codigo_ibge\n")
    manifest = serving.prepare_serving(2026, root=tmp_path)
    assert manifest["geografia"] == {
        "municipios": True, "de_para": True, "zonas_poligonos": False
    }
    saved = json.loads((tmp_path / "serving" / "2026" / "catalog.json").read_text())
    assert saved["geografia"] == manifest["geografia"]



def test_coverage_catalog_distinguishes_missing_state_and_second_turn(tmp_path):
    values = rows("RR")
    values["cargo"] = ["Presidente", "Presidente", "Presidente"]
    values["turno"] = [1, 1, 1]
    make_source(tmp_path, "BR", values)
    catalog = serving.prepare_serving(2026, root=tmp_path)
    coverage = catalog["cobertura"]
    assert coverage["ufs_importadas"] == 0
    assert coverage["ufs_esperadas"] == 27
    assert "PR" in coverage["ufs_ausentes"]
    assert coverage["arquivo_presidencial"] is True
    assert coverage["turnos_presidente"] == [1]
    assert coverage["completo_em_ufs"] is False
