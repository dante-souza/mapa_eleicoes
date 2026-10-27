"""Cenario completo de staging, ZIP bundle e make prepare-data."""
from __future__ import annotations

import csv
import io
import json
import zipfile

import pytest

from mapa_eleicoes import cli, pipeline


def make_zip(path, headers, rows):
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(headers)
    writer.writerows(rows)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(path.stem + ".csv", buf.getvalue().encode("latin-1"))
    return path


@pytest.fixture
def storage(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setattr(cli, "DATA", root)
    monkeypatch.setattr(pipeline, "DATA", root)
    return root


def section(path):
    return make_zip(
        path,
        ["ANO_ELEICAO", "NR_TURNO", "SG_UF", "CD_MUNICIPIO",
         "NM_MUNICIPIO", "NR_ZONA", "NR_SECAO", "DS_CARGO",
         "NR_VOTAVEL", "NM_VOTAVEL", "QT_VOTOS"],
        [["2026", "1", "RR", "03010", "BOA VISTA", "1", "10",
          "Governador", "13", "EXEMPLO", "10"]],
    )


def aux(path):
    return make_zip(
        path,
        ["ANO_ELEICAO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA",
         "NM_URNA_CANDIDATO", "QT_VOTOS_NOMINAIS"],
        [["2026", "RR", "03010", "1", "EXEMPLO", "10"]],
    )


def test_prepare_auto_imports_sections_and_munzona(storage):
    section(storage / "votacao_secao_2026_RR.zip")
    aux(storage / "votacao_candidato_munzona_2026.zip")
    result = pipeline.prepare(2026)
    assert result["erros"] == []
    assert "votacao_secao_2026_RR.zip" in result["secoes"]
    assert "votacao_candidato_munzona_2026.zip" in result["munzona"]
    aggregate = storage / "processed" / "2026" / "votos_RR.csv.gz"
    parquet = storage / "processed" / "2026" / "aux" / "votacao_candidato_munzona_2026" / "part-000001.parquet"
    assert aggregate.exists()
    assert parquet.exists()
    before = (aggregate.stat().st_mtime_ns, parquet.stat().st_mtime_ns)
    pipeline.prepare(2026)
    assert (aggregate.stat().st_mtime_ns, parquet.stat().st_mtime_ns) == before
    metadata = json.loads((parquet.parent / "manifest.json").read_text(encoding="utf-8"))
    assert metadata["linhas"] == 1
    assert "QT_VOTOS_NOMINAIS" in metadata["colunas"]


def test_bundle_roundtrip(storage):
    raw = storage / "raw" / "2026"
    raw.mkdir(parents=True)
    data = section(raw / "votacao_secao_2026_RR.zip")
    expected = cli.hash_file(data)
    output = pipeline.pack(2026)
    assert output.exists()
    data.unlink()
    items = pipeline.unpack(output, 2026)
    assert items == ["votacao_secao_2026_RR.zip"]
    assert cli.hash_file(data) == expected
    assert pipeline.unpack(output, 2026) == []


def test_bundle_refuses_year_mismatch(storage):
    raw = storage / "raw" / "2026"
    raw.mkdir(parents=True)
    section(raw / "votacao_secao_2026_RR.zip")
    bundle = pipeline.pack(2026)
    with pytest.raises(ValueError, match="Ano"):
        pipeline.unpack(bundle, 2022)


def test_legacy_ingest_ignores_auxiliary_zip(storage):
    raw = storage / "raw" / "2026"
    raw.mkdir(parents=True)
    section(raw / "votacao_secao_2026_RR.zip")
    aux(raw / "votacao_candidato_munzona_2026.zip")
    results, errors = cli.ingest(2026)
    assert errors == []
    assert len(results) == 1
    assert results[0]["uf"] == "RR"


def test_corrupt_zip_stops_prepare_and_records_manifest(storage):
    section(storage / "votacao_secao_2026_RR.zip")
    broken = storage / "votacao_secao_2026_PR.zip"
    broken.write_bytes(b"broken")
    with pytest.raises(ValueError, match="Preparacao incompleta"):
        pipeline.prepare(2026)
    summary = json.loads(
        (storage / "processed" / "2026" / "prepare_manifest.json").read_text(encoding="utf-8")
    )
    assert summary["erros"]
    assert "votacao_secao_2026_RR.zip" in summary["secoes"]
