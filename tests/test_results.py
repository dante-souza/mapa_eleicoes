"""1o/2o colocados, margem em p.p., empate e denominador de validos."""
from __future__ import annotations

import polars as pl
import pytest

from mapa_eleicoes.results import br_number, margin_class, region_results
from mapa_eleicoes.vote_gradients import TIE, NO_DATA, legend_html, margin_shade
from mapa_eleicoes.party_colors import PT_RED, PL_BLUE


def frame(rows):
    return pl.DataFrame(
        rows, schema=["map_id", "numero", "candidato", "tipo_voto", "votos"],
        orient="row",
    )


def test_second_round_margin_and_shares():
    data = frame([
        ("A", "13", "LULA", "nominal", 808),
        ("A", "22", "FLAVIO", "nominal", 192),
        ("A", "95", "Branco", "branco", 50),
        ("A", "96", "Nulo", "nulo", 30),
    ])
    row = region_results(data, ["map_id"]).row(0, named=True)
    assert row["candidato_1"] == "LULA" and row["candidato_2"] == "FLAVIO"
    # Branco e nulo nao entram no denominador de validos.
    assert row["total_validos"] == 1000
    assert row["pct_1"] == pytest.approx(80.8)
    assert row["pct_2"] == pytest.approx(19.2)
    assert row["margem_pp"] == pytest.approx(61.6)
    assert row["empate"] is False


def test_legenda_counts_in_valid_denominator_not_in_ranking():
    data = frame([
        ("A", "1301", "FULANO", "nominal", 60),
        ("A", "2201", "BELTRANO", "nominal", 20),
        ("A", "13", "PT", "legenda", 20),
    ])
    row = region_results(data, ["map_id"]).row(0, named=True)
    assert row["total_validos"] == 100
    assert row["pct_1"] == pytest.approx(60.0)
    assert row["candidato_2"] == "BELTRANO"


def test_tie_is_explicit_and_single_candidate_has_full_margin():
    data = frame([
        ("A", "13", "X", "nominal", 50),
        ("A", "22", "Y", "nominal", 50),
        ("B", "22", "Y", "nominal", 10),
    ])
    out = {r["map_id"]: r for r in region_results(data, ["map_id"]).iter_rows(named=True)}
    assert out["A"]["empate"] is True
    assert out["A"]["margem_pp"] == pytest.approx(0.0)
    assert out["B"]["candidato_2"] is None
    assert out["B"]["margem_pp"] == pytest.approx(100.0)
    assert out["B"]["empate"] is False


def test_margin_classes_and_colors_keep_party_hue_even_when_close():
    # Classes do g1: 0-5, 5-20, acima de 20 p.p.
    assert [margin_class(v) for v in (0, 4.9, 5, 10, 19.9, 20, 80)] == [0, 0, 1, 1, 1, 2, 2]
    assert margin_class(None) is None and margin_class(float("nan")) is None
    assert margin_shade("13", 40) == PT_RED
    assert margin_shade("22", 40) == PL_BLUE
    weak_red, weak_blue = margin_shade("13", 1), margin_shade("22", 1)
    # Margem apertada ainda separa vermelho de azul pelo matiz dominante.
    assert int(weak_red[1:3], 16) > int(weak_red[5:7], 16)
    assert int(weak_blue[5:7], 16) > int(weak_blue[1:3], 16)
    assert [margin_shade("13", v) for v in (1, 7, 40)] == ["#f3b5bf", "#e66b7e", "#d60828"]
    assert [margin_shade("22", v) for v in (1, 7, 40)] == ["#bec0e0", "#7d81c1", "#272d97"]
    # Candidato com numero 13xxx (ex.: deputado) usa a mesma paleta da legenda.
    assert margin_shade("1312", 7) == "#e66b7e"
    # Demais legendas: tres niveis distintos da cor propria.
    assert len({margin_shade("45", v) for v in (1, 7, 40)}) == 3
    assert margin_shade("13", 30, tie=True) == TIE
    assert margin_shade("13", None) == NO_DATA


def test_margin_legend_lists_classes_and_tie():
    html = legend_html("margem")
    assert "2º colocado" in html and "Empate" in html
    assert "acima de 20 p.p." in html and PT_RED in html and PL_BLUE in html


def test_brazilian_number_format():
    assert br_number(12345.678) == "12.345,68"
    assert br_number(12345, 0) == "12.345"
    assert br_number(None) == "—" and br_number(float("nan")) == "—"
