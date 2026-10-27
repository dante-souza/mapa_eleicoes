from __future__ import annotations

import csv
import gzip
import io
import json
import zipfile
from pathlib import Path

import polars as pl
import pytest

from mapa_eleicoes import cli

HEADERS = [
    "ANO_ELEICAO", "NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO",
    "NR_ZONA", "NR_SECAO", "DS_CARGO", "NR_VOTAVEL", "NM_VOTAVEL", "QT_VOTOS",
]
ROWS = [
    ["2026", "1", "RR", "03010", "BOA VISTA", "1", "10", "Governador", "13", "CANDIDATO A", "10"],
    ["2026", "1", "RR", "03010", "BOA VISTA", "1", "11", "Governador", "13", "CANDIDATO A", "20"],
    ["2026", "1", "RR", "03010", "BOA VISTA", "1", "11", "Governador", "22", "CANDIDATO B", "19"],
    ["2026", "1", "RR", "03010", "BOA VISTA", "1", "10", "Governador", "95", "Voto em branco", "2"],
    ["2026", "2", "RR", "03010", "BOA VISTA", "1", "10", "Governador", "13", "CANDIDATO A", "12"],
]


def sample_zip(path: Path):
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(HEADERS)
    writer.writerows(ROWS)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("votacao_secao_2026_RR.csv", buf.getvalue().encode("latin-1"))
        archive.writestr("leiame.pdf", b"%PDF-1.4")
    return path


def read_votes(path: Path) -> pl.DataFrame:
    with gzip.open(path, "rb") as stream:
        return pl.read_csv(stream, infer_schema=False).with_columns(
            pl.col("votos").cast(pl.Int64),
            pl.col("turno").cast(pl.Int16),
            pl.col("zona").cast(pl.Int32),
        )


def test_archive_inspect(tmp_path):
    result = cli.inspect_archive(sample_zip(tmp_path / "votacao_secao_2026_RR.zip"))
    assert len(result["csvs"]) == 1
    assert len(result["csvs"][0]["colunas"]) == len(HEADERS)
    assert result["csvs"][0]["exemplo"]["SG_UF"] == "RR"


def test_archive_corrupt(tmp_path):
    path = tmp_path / "votacao_secao_2026_PR.zip"
    path.write_bytes(b"PK-not-a-zip")
    with pytest.raises(ValueError, match="invalido/incompleto"):
        cli.ensure_archive(path)


def test_zone_aggregation_separated_by_turno(tmp_path):
    path = sample_zip(tmp_path / "votacao_secao_2026_RR.zip")
    meta = cli.process_archive(path, 2026, tmp_path / "result", chunksize=2)
    assert meta["linhas_lidas"] == 5
    assert meta["turnos"] == [1, 2]
    out = read_votes(tmp_path / "result" / "votos_RR.csv.gz")
    assert out.get_column("votos").sum() == 63
    first = out.filter((pl.col("turno") == 1) & (pl.col("numero") == "13"))
    assert first.get_column("votos").sum() == 30
    assert out.filter(pl.col("tipo_voto") == "branco").get_column("votos").sum() == 2
    assert out.get_column("cd_municipio_tse").unique().to_list() == ["3010"]
    assert out.schema["votos"] == pl.Int64
    assert out.schema["numero"] == pl.String
    assert json.loads((tmp_path / "result" / "votos_RR.json").read_text())["total_votos_linhas"] == 63


def test_wrong_year_errors(tmp_path):
    path = sample_zip(tmp_path / "votacao_secao_2026_RR.zip")
    with pytest.raises(ValueError, match="nenhuma linha util"):
        cli.process_archive(path, 2022, tmp_path / "output")


def test_import_is_repeatable(tmp_path):
    path = sample_zip(tmp_path / "votacao_secao_2026_RR.zip")
    destination = tmp_path / "raw"
    assert cli.import_archive(path, 2026, destination).exists()
    assert cli.import_archive(path, 2026, destination).exists()


def test_crosswalk_leading_zero_and_utf8(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "DATA", tmp_path)
    source = tmp_path / "codigos.csv"
    source.write_text(
        "SG_UF;CD_MUNICIPIO_TSE;CD_MUNICIPIO_IBGE\nRR;03010;1400100\n",
        encoding="utf-8",
    )
    cli.crosswalk_import(source)
    frame = pl.read_csv(tmp_path / "reference" / "tse_ibge.csv", infer_schema=False)
    assert frame.row(0, named=True)["cd_municipio_tse"] == "3010"
    assert frame.row(0, named=True)["codigo_ibge"] == "1400100"
    assert frame.schema["codigo_ibge"] == pl.String


def test_validate_aggregated_votes(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "DATA", tmp_path)
    path = sample_zip(tmp_path / "votacao_secao_2026_RR.zip")
    cli.process_archive(path, 2026, tmp_path / "processed" / "2026", chunksize=2)
    cli.validate(2026)


def test_reject_negative_votes(tmp_path):
    path = tmp_path / "votacao_secao_2026_RR.zip"
    row = ROWS[0].copy()
    row[-1] = "-1"
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(HEADERS)
    writer.writerow(row)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("x.csv", buffer.getvalue().encode("latin-1"))
    with pytest.raises(ValueError, match="votos negativos"):
        cli.process_archive(path, 2026, tmp_path / "out", chunksize=1)
