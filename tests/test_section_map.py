"""Seções: persistência independente, coords oficiais e resultados por local."""
from __future__ import annotations

import csv
import io
import zipfile

import polars as pl
import pytest

from mapa_eleicoes import polling_locations, section_serving, section_map


def build_results(path):
    header = [
        "ANO_ELEICAO", "NR_TURNO", "SG_UF", "CD_MUNICIPIO",
        "NM_MUNICIPIO", "NR_ZONA", "NR_SECAO", "DS_CARGO",
        "NR_VOTAVEL", "NM_VOTAVEL", "QT_VOTOS",
    ]
    data = [
        ["2026", "1", "RR", "03010", "BOA VISTA", "1", "10",
         "Presidente", "13", "A", "21"],
        ["2026", "1", "RR", "03010", "BOA VISTA", "1", "10",
         "Presidente", "22", "B", "9"],
        ["2026", "1", "RR", "03010", "BOA VISTA", "1", "11",
         "Presidente", "13", "A", "7"],
        ["2026", "1", "RR", "03010", "BOA VISTA", "1", "11",
         "Presidente", "22", "B", "23"],
        ["2026", "1", "RR", "03010", "BOA VISTA", "1", "11",
         "Presidente", "95", "Voto em branco", "2"],
    ]
    stream = io.StringIO()
    writer = csv.writer(stream, delimiter=";")
    writer.writerow(header)
    writer.writerows(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("votacao_secao_2026_RR.csv", stream.getvalue().encode("latin-1"))
    return path


def build_locations(path):
    fields = [
        "NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO",
        "NR_LOCAL_VOTACAO", "NM_LOCAL_VOTACAO", "DS_ENDERECO",
        "NR_LATITUDE", "NR_LONGITUDE",
    ]
    entries = [
        ["1", "RR", "03010", "1", "10", "100", "ESCOLA A",
         "RUA X", "2,5", "-60,5"],
        ["1", "RR", "03010", "1", "11", "100", "ESCOLA A",
         "RUA X", "2,5", "-60,5"],
        ["2", "RR", "03010", "1", "11", "200", "ESCOLA B",
         "RUA Y", "2,6", "-60,7"],
    ]
    stream = io.StringIO()
    writer = csv.writer(stream, delimiter=";")
    writer.writerow(fields)
    writer.writerows(entries)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("eleitorado_local_votacao_2026_RR.csv",
                         stream.getvalue().encode("latin-1"))
    return path


def test_section_ingestion_does_not_collapse_two_sections(tmp_path):
    source = build_results(tmp_path / "raw" / "2026" / "votacao_secao_2026_RR.zip")
    catalog = section_serving.prepare_sections(2026, root=tmp_path)
    data = pl.read_parquet(tmp_path / "serving" / "2026" / "secoes" / "secoes_RR.parquet")
    assert catalog["fontes"][source.name]["linhas_origem"] == 5
    assert data.filter(pl.col("tipo_voto") == "nominal")["votos"].sum() == 60
    assert set(data["secao"].to_list()) == {10, 11}
    assert data.filter(pl.col("tipo_voto") == "branco")["votos"].sum() == 2
    # Cache incremental por origem.
    again = section_serving.prepare_sections(2026, root=tmp_path)
    assert again["fontes"][source.name]["sha256"] == catalog["fontes"][source.name]["sha256"]


def test_official_coordinates_align_by_municipio_zona_secao_and_round(tmp_path):
    build_results(tmp_path / "raw" / "2026" / "votacao_secao_2026_RR.zip")
    section_serving.prepare_sections(2026, root=tmp_path)
    source = build_locations(tmp_path / "source" / "eleitorado_local_votacao_2026.zip")
    polling_locations.prepare_locations(2026, root=tmp_path, source=source)
    votes = section_map.load_sections(
        tmp_path, 2026, "RR", ["3010"], "Presidente", 1
    )
    places = section_map.load_locations(tmp_path, 2026, "RR", ["3010"], 1)
    assert votes.schema["turno"] == places.schema["turno"] == pl.Int16
    assert votes.schema["zona"] == places.schema["zona"] == pl.Int32
    assert votes.schema["secao"] == places.schema["secao"] == pl.Int32
    rows, sites, no_geo = section_map.section_detail(votes, places)
    assert rows.height == 2
    assert no_geo == 0
    assert sites.height == 1
    assert sites.row(0, named=True)["n_secoes"] == 2
    # 28 de 60 nominais ao numero 13, 32 ao 22; o lugar tende a azul.
    assert sites.row(0, named=True)["numero_lider"] == "22"
    assert sites.row(0, named=True)["pct_lider"] == pytest.approx(32/60*100)
    mapa, total, hidden = section_map.render_site_points(rows, sites)
    assert total == 1 and hidden == 0
    html = mapa.get_root().render()
    assert "ESCOLA A" in html
    assert "Seção" in html or "Se\\u00e7\\u00e3o" in html


def test_missing_official_geolocation_keeps_section_in_tabular_results(tmp_path):
    assert polling_locations.normalize_location({
        "SG_UF": "RR", "CD_MUNICIPIO": "3010", "NR_ZONA": "1",
        "NR_SECAO": "10", "NR_TURNO": "1",
        "NR_LATITUDE": "-1", "NR_LONGITUDE": "-1",
    }) is None
    votes = pl.DataFrame({
        "uf": ["RR"], "cd_municipio_tse": ["3010"],
        "zona": [1], "secao": [10], "turno": [1],
        "tipo_voto": ["nominal"], "numero": ["13"],
        "candidato": ["A"], "votos": [21],
    })
    sec, sites, no_geo = section_map.section_detail(votes, pl.DataFrame())
    assert sec.is_empty() and sites.is_empty() and no_geo == 1


def test_distinct_poll_places_required_for_same_section_round():
    places = pl.DataFrame({
        "uf": ["RR", "RR"], "cd_municipio_tse": ["3010", "3010"],
        "zona": [1, 1], "secao": [10, 10], "turno": [1, 1],
        "local": ["100", "200"], "nome_local": ["A", "B"],
        "endereco": ["X", "Y"], "latitude": [2.0, 2.1],
        "longitude": [-60.0, -60.1],
    })
    votes = pl.DataFrame({
        "uf": ["RR"], "cd_municipio_tse": ["3010"],
        "zona": [1], "secao": [10], "turno": [1],
        "tipo_voto": ["nominal"], "numero": ["13"],
        "candidato": ["A"], "votos": [21],
    })
    with pytest.raises(ValueError, match="multiplos locais"):
        section_map.section_detail(votes, places)
