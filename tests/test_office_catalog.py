"""Regression tests for selecting offices independently from election round."""
from __future__ import annotations

import gzip

import polars as pl
import pytest

from mapa_eleicoes.office_catalog import (
    available_offices, available_turns, preferred_office,
    office_inventory, print_office_inventory,
)


@pytest.fixture()
def full_sample():
    return pl.DataFrame({
        "uf": ["RR", "RR", "RR", "RR", "RR", "SP"],
        "cargo": [
            "Governador", "Governador", "Deputado federal",
            "Senador", "Presidente", "Presidente",
        ],
        "turno": [1, 2, 1, 1, 1, 2],
        "votos": [25, 17, 20, 15, 30, 35],
    })


def test_offices_do_not_disappear_when_second_round_is_selected(full_sample):
    offices = available_offices(full_sample)
    assert offices == ["Presidente", "Governador", "Senador", "Deputado federal"]
    assert available_turns(full_sample, "Governador") == [1, 2]
    assert available_turns(full_sample, "Deputado federal") == [1]
    assert available_turns(full_sample, "Senador") == [1]
    assert available_turns(full_sample, "Presidente") == [1, 2]


def test_president_is_default_if_present(full_sample):
    choices = available_offices(full_sample)
    assert choices[preferred_office(choices)] == "Presidente"


def test_no_president_is_not_fabricated(full_sample):
    frame = full_sample.filter(pl.col("cargo") != "Presidente")
    choices = available_offices(frame)
    assert "Presidente" not in choices
    assert choices[preferred_office(choices)] == "Governador"


def test_scope_to_uf_before_offices_and_turns(full_sample):
    scoped = full_sample.filter(pl.col("uf") == "RR")
    assert available_turns(scoped, "Presidente") == [1]
    assert available_turns(scoped, "Governador") == [1, 2]
    assert "Deputado federal" in available_offices(scoped)


def test_empty_and_missing_values():
    empty = pl.DataFrame({"cargo": [], "turno": []}, schema={"cargo": pl.String, "turno": pl.Int16})
    assert available_offices(empty) == []
    assert available_turns(empty, "Governador") == []
    assert preferred_office([]) == 0
    missing = pl.DataFrame({"cargo": ["", None, "Senador"], "turno": [1, 1, 1]})
    assert available_offices(missing) == ["Senador"]


def test_inventory_displays_offices_by_round_and_detects_br(tmp_path, capsys):
    processed = tmp_path / "processed" / "2026"
    processed.mkdir(parents=True)
    sample = pl.DataFrame({
        "uf": ["RR", "RR", "RR"],
        "cargo": ["Governador", "Governador", "Deputado federal"],
        "turno": [1, 2, 1],
        "votos": [50, 30, 40],
    })
    with gzip.open(processed / "votos_RR.csv.gz", "wt", encoding="utf-8") as stream:
        sample.write_csv(stream)
    with gzip.open(processed / "votos_BR.csv.gz", "wt", encoding="utf-8") as stream:
        pl.DataFrame({
            "uf": ["RR"], "cargo": ["Presidente"], "turno": [1], "votos": [90]
        }).write_csv(stream)
    rows = office_inventory(2026, root=tmp_path)
    assert rows.height == 4
    print_office_inventory(2026, root=tmp_path)
    stdout = capsys.readouterr().out
    assert "Turno 2 / Governador" in stdout
    assert "Turno 1 / Deputado federal" in stdout
    assert "Fonte BR: Presidente (turno 1)" in stdout


def test_inventory_reports_missing_br_without_claiming_president(tmp_path, capsys):
    processed = tmp_path / "processed" / "2026"
    processed.mkdir(parents=True)
    with gzip.open(processed / "votos_RR.csv.gz", "wt", encoding="utf-8") as stream:
        pl.DataFrame({"uf": ["RR"], "cargo": ["Governador"], "turno": [2], "votos": [42]}).write_csv(stream)
    print_office_inventory(2026, root=tmp_path)
    assert "votos_BR.csv.gz ausente" in capsys.readouterr().out


def test_inventory_requires_files(tmp_path):
    with pytest.raises(FileNotFoundError, match="Sem votos processados"):
        office_inventory(2026, root=tmp_path)
