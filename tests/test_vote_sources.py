"""Arquivo nacional BR e arquivos estaduais nunca somam o mesmo voto."""
from __future__ import annotations

import polars as pl

from mapa_eleicoes.vote_sources import combine_sources

COLUMNS = ["uf", "cargo", "turno", "zona", "numero", "votos"]


def votes(rows):
    return pl.DataFrame(rows, schema=COLUMNS, orient="row")


def test_president_in_both_br_and_state_files_is_counted_once():
    br = votes([("SP", "Presidente", 1, 1, "13", 100),
                ("RJ", "Presidente", 1, 5, "22", 70)])
    sp = votes([("SP", "Presidente", 1, 1, "13", 100),
                ("SP", "Governador", 1, 1, "45", 80)])
    combined, dropped = combine_sources({"BR": br, "SP": sp})
    assert dropped == 1
    president_sp = combined.filter(
        (pl.col("uf") == "SP") & (pl.col("cargo") == "Presidente")
    )
    assert president_sp["votos"].sum() == 100
    # Cargos que so existem no arquivo estadual permanecem.
    assert combined.filter(pl.col("cargo") == "Governador").height == 1


def test_state_file_kept_when_br_does_not_cover_that_combination():
    # BR so com o 1o turno: 2o turno estadual nao pode sumir.
    br = votes([("SP", "Presidente", 1, 1, "13", 100)])
    sp = votes([("SP", "Presidente", 2, 1, "13", 90)])
    combined, dropped = combine_sources({"BR": br, "SP": sp})
    assert dropped == 0
    assert combined.height == 2


def test_without_br_all_state_rows_are_kept():
    sp = votes([("SP", "Presidente", 1, 1, "13", 100)])
    rj = votes([("RJ", "Presidente", 1, 5, "22", 70)])
    combined, dropped = combine_sources({"SP": sp, "RJ": rj})
    assert (combined.height, dropped) == (2, 0)
    assert combine_sources({})[0].is_empty()
