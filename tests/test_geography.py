"""Regressoes de cobertura municipal IBGE/TSE sem depender de rede."""
from __future__ import annotations

import gzip
import io
import json
import zipfile

import geopandas as gpd
import polars as pl
import pytest
from shapely.geometry import Polygon

from mapa_eleicoes import cli, geography


@pytest.fixture
def storage(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setattr(cli, "DATA", root)
    monkeypatch.setattr(geography, "DATA", root)
    return root


def test_crosswalk_official_without_uf_deduces_from_ibge_code(storage):
    source = storage / "codigo_municipio_tse_ibge.csv"
    source.write_text(
        "CD_MUNICIPIO_TSE;CD_MUNICIPIO_IBGE\n"
        "71072;3550308\n"
        "03010;1400100\n", encoding="utf-8",
    )
    cli.crosswalk_import(source)
    mapped = pl.read_csv(storage / "reference" / "tse_ibge.csv", infer_schema=False)
    assert mapped.height == 2
    lookup = {(row["uf"], row["cd_municipio_tse"]): row["codigo_ibge"]
              for row in mapped.iter_rows(named=True)}
    assert lookup[("SP", "71072")] == "3550308"
    assert lookup[("RR", "3010")] == "1400100"
    assert mapped.schema["codigo_ibge"] == pl.String


def test_crosswalk_rejects_conflicting_uf(storage):
    source = storage / "bad.csv"
    source.write_text(
        "SG_UF;CD_MUNICIPIO_TSE;CD_MUNICIPIO_IBGE\n"
        "RJ;71072;3550308\n", encoding="utf-8",
    )
    with pytest.raises(ValueError, match="UF original discorda"):
        cli.crosswalk_import(source)


def test_crosswalk_rejects_ambiguous_mapping(storage):
    source = storage / "ambiguous.csv"
    source.write_text(
        "CD_MUNICIPIO_TSE;CD_MUNICIPIO_IBGE\n"
        "71072;3550308\n"
        "71072;3509502\n", encoding="utf-8",
    )
    with pytest.raises(ValueError, match="multiplos municipios"):
        cli.crosswalk_import(source)


def test_crosswalk_accepts_zip_and_comma_separator(storage):
    archive_path = storage / "codes.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "municipios.csv", "codigo_tse,codigo_ibge\n71072,3550308\n"
        )
    cli.crosswalk_import(archive_path)
    result = pl.read_csv(storage / "reference" / "tse_ibge.csv", infer_schema=False)
    assert result.row(0, named=True)["uf"] == "SP"


def sample_geometry(storage):
    mesh = storage / "synthetic_ibge.geojson"
    polygons = gpd.GeoDataFrame(
        {"CD_MUN": ["3550308", "1400100"],
         "geometry": [
             Polygon([(-47.0, -24.0), (-46.0, -24.0), (-46.0, -23.0), (-47.0, -23.0)]),
             Polygon([(-61.0, 2.0), (-60.0, 2.0), (-60.0, 3.0), (-61.0, 3.0)]),
         ]},
        crs="EPSG:4326",
    )
    polygons.to_file(mesh, driver="GeoJSON")
    return mesh


def test_geography_offline_setup_and_coverage(storage):
    crosswalk = storage / "crosswalk.csv"
    crosswalk.write_text(
        "SG_UF;CODIGO_TSE;CODIGO_IBGE\n"
        "SP;71072;3550308\n"
        "RR;03010;1400100\n", encoding="utf-8",
    )
    mesh = sample_geometry(storage)
    result = geography.setup(2025, crosswalk=crosswalk, malha=mesh, simplify_meters=0)
    assert result["de_para"]["linhas"] == 2
    assert result["geometrias_disponiveis"] == 2
    geojson_path = storage / "geo" / "municipios.geojson"
    output = gpd.read_file(geojson_path)
    assert sorted(output["codigo_ibge"].to_list()) == ["1400100", "3550308"]
    assert output.crs.to_epsg() == 4326
    assert json.loads((storage / "geo" / "official_sources.json").read_text())["ano_malha_ibge"] == 2025

    votes_path = storage / "processed" / "2026" / "votos_RR.csv.gz"
    votes_path.parent.mkdir(parents=True)
    with gzip.open(votes_path, "wt", encoding="utf-8") as out:
        out.write("uf,cd_municipio_tse\nRR,3010\nSP,71072\nXX,9999\n")
    coverage = geography.coverage(2026)
    assert coverage["total_chaves_tse"] == 3
    assert coverage["nao_mapeadas_tse_ibge"] == 1
    assert coverage["sem_poligono_ibge"] == 0


def test_geo_ids_are_not_joined_by_names(storage):
    mesh = sample_geometry(storage)
    result = geography.build_municipal_geojson(
        mesh, storage / "geo" / "municipios.geojson", simplify_meters=500
    )
    assert result["municipios"] == 2
    assert result["fonte_coluna"] == "CD_MUN"


def test_cached_zip_no_network(storage, monkeypatch):
    path = storage / "geo" / "source" / "test.zip"
    path.parent.mkdir(parents=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("x.txt", "local")
    monkeypatch.setattr(geography, "urlopen",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("network")))
    assert geography.download("https://example.com/test.zip", path) == path


def test_crosswalk_official_full_column_layout(storage):
    """Replica a estrutura oficial: horarios, sigla UF, codigos TSE/IBGE."""
    source = storage / "municipio_tse_ibge.csv"
    source.write_text(
        "DT_GERACAO;HH_GERACAO;CD_UF_TSE;CD_UF_IBGE;SG_UF;NM_UF;"
        "CD_MUNICIPIO_TSE;NM_MUNICIPIO_TSE;CD_MUNICIPIO_IBGE;NM_MUNICIPIO_IBGE\n"
        "10/05/2026;09:01:10;24;12;AC;Acre;1007;Bujari;1200138;Bujari\n",
        encoding="utf-8",
    )
    cli.crosswalk_import(source)
    values = pl.read_csv(storage / "reference" / "tse_ibge.csv", infer_schema=False)
    assert values.row(0, named=True) == {
        "cd_municipio_tse": "1007", "codigo_ibge": "1200138", "uf": "AC"
    }
