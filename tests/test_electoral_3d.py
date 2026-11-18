"""Teste da camada experimental 3D: votos, chaves e integridade BR/UF."""
from pathlib import Path

import geopandas as gpd
import polars as pl
import pytest
from shapely.geometry import Point, Polygon

from mapa_eleicoes.electoral_3d import (
    columns_for_map, load_geometry, load_reference, load_votes, municipal_totals,
)


def votes(rows):
    return pl.DataFrame(rows, schema=[
        "uf", "cd_municipio_tse", "municipio", "cargo", "turno",
        "numero", "candidato", "tipo_voto", "votos",
    ], orient="row")


def sample():
    rows = votes([
        ("SP", "0001", "A", "Presidente", 2, "13", "X", "nominal", 80),
        ("SP", "0001", "A", "Presidente", 2, "22", "Y", "nominal", 20),
        ("SP", "0002", "B", "Presidente", 2, "13", "X", "nominal", 30),
        ("SP", "0002", "B", "Presidente", 2, "22", "Y", "nominal", 50),
        ("SP", "0002", "B", "Presidente", 2, "13", "PT", "legenda", 20),
        ("SP", "0002", "B", "Presidente", 2, "96", "NULO", "nulo", 80),
    ])
    refs = pl.DataFrame({
        "uf": ["SP", "SP"], "cd_municipio_tse": ["0001", "0002"],
        "codigo_ibge": ["3550308", "3509502"],
    })
    coords = pl.DataFrame({
        "codigo_ibge": ["3550308", "3509502"],
        "longitude": [-46.6, -47.0], "latitude": [-23.5, -22.9],
    })
    return rows, refs, coords


def test_margem_com_votos_validos_e_codigo_ibge():
    frame, refs, _ = sample()
    result = municipal_totals(frame, refs, candidate="13")
    rows = {row["cd_municipio_tse"]: row for row in result.iter_rows(named=True)}
    assert rows["0001"]["margem_votos"] == 60
    assert rows["0001"]["margem_pp"] == pytest.approx(60)
    assert rows["0001"]["codigo_ibge"] == "3550308"
    assert rows["0002"]["numero_1"] == "22"
    assert rows["0002"]["margem_votos"] == 20
    assert rows["0002"]["margem_pp"] == pytest.approx(20)
    assert rows["0002"]["total_validos"] == 100  # nulos fora; legenda dentro


def test_colunas_modo_e_cores_estaveis():
    frame, refs, coords = sample()
    totals = municipal_totals(frame, refs, candidate="13")
    rows, info = columns_for_map(totals, coords, "Margem de votos")
    by_code = {row["codigo_ibge"]: row for row in rows}
    assert len(rows) == 2 and info["sem_de_para"] == 0
    assert by_code["3550308"]["color"][:3] == [214, 8, 40]
    assert by_code["3509502"]["color"][:3] == [39, 45, 151]
    assert by_code["3550308"]["metrica"] == "60 votos"
    assert max(row["elevation"] for row in rows) <= 160000
    percent, _ = columns_for_map(totals, coords, "Margem percentual")
    assert {r["codigo_ibge"]: r["metrica"] for r in percent}["3509502"] == "20,00 p.p."
    candidates, _ = columns_for_map(totals, coords, "Votos do candidato", candidate="13")
    assert all(r["color"][:3] == [214, 8, 40] for r in candidates)
    assert {r["codigo_ibge"]: r["metrica"] for r in candidates}["3509502"] == "30 votos"


def test_sem_correspondencia_nao_inventa_coordenadas():
    frame, refs, coords = sample()
    result = municipal_totals(frame, refs.head(1))
    rows, diag = columns_for_map(
        result, coords.filter(pl.col("codigo_ibge") != "3550308"), "Margem de votos",
    )
    assert rows == []
    assert diag["sem_de_para"] == 1
    assert diag["sem_geometria"] == 1


def test_de_para_ambiguo_e_rejeitado():
    frame, refs, _ = sample()
    conflicting = pl.concat([refs, pl.DataFrame({
        "uf": ["SP"], "cd_municipio_tse": ["0001"], "codigo_ibge": ["3550309"],
    })])
    with pytest.raises(ValueError, match="ambiguo"):
        municipal_totals(frame, conflicting)


def test_malha_usa_ponto_no_interior(tmp_path):
    donut = Polygon(
        [(0, 0), (4, 0), (4, 4), (0, 4)],
        holes=[[(1, 1), (3, 1), (3, 3), (1, 3)]],
    )
    other = Polygon([(5, 0), (6, 0), (6, 1), (5, 1)])
    geo = gpd.GeoDataFrame({
        "codigo_ibge": ["3550308", "3304557"], "geometry": [donut, other],
    }, crs="EPSG:4326")
    folder = tmp_path / "geo"
    folder.mkdir()
    geo.to_file(folder / "municipios.geojson", driver="GeoJSON")
    coords, states = load_geometry(tmp_path)
    point = coords.filter(pl.col("codigo_ibge") == "3550308").row(0, named=True)
    assert donut.contains(Point(point["longitude"], point["latitude"]))
    assert len(states["features"]) == 2


def test_precedencia_nacional_preserva_cargo_estadual(tmp_path):
    folder = tmp_path / "serving" / "2026"
    folder.mkdir(parents=True)
    votes([("SP", "0001", "A", "Presidente", 2, "13", "X", "nominal", 80)]).write_parquet(
        folder / "votos_BR.parquet")
    votes([
        ("SP", "0001", "A", "Presidente", 2, "13", "X", "nominal", 80),
        ("SP", "0001", "A", "Governador", 1, "13", "Z", "nominal", 50),
    ]).write_parquet(folder / "votos_SP.parquet")
    result, discarded = load_votes(tmp_path, 2026)
    assert discarded == 1
    assert result.filter(pl.col("cargo") == "Presidente")["votos"].sum() == 80
    assert result.filter(pl.col("cargo") == "Governador")["votos"].sum() == 50


def test_crosswalk_nao_perde_zeros_do_codigo_tse(tmp_path):
    folder = tmp_path / "reference"
    folder.mkdir()
    (folder / "tse_ibge.csv").write_text(
        "uf,cd_municipio_tse,codigo_ibge\nSP,0001,3550308\n", encoding="utf-8",
    )
    assert load_reference(tmp_path)["cd_municipio_tse"][0] == "0001"
