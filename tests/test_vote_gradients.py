"""Regressoes de intensidade cromatica dos resultados do Atlas."""
from __future__ import annotations

from mapa_eleicoes.vote_gradients import NO_DATA, PALE, legend_html, percentage_shade
from mapa_eleicoes.party_colors import PT_RED, PL_BLUE


def test_percent_0_to_100_keeps_red_and_blue_hues():
    assert percentage_shade("13", 0) == PALE
    assert percentage_shade("22", 0) == PALE
    assert percentage_shade("13", 100) == PT_RED
    assert percentage_shade("22", 100) == PL_BLUE
    red_30 = percentage_shade("13", 30)
    red_80 = percentage_shade("13", 80)
    assert red_30 != red_80
    assert percentage_shade("22", 30) != percentage_shade("22", 80)


def test_percent_clamped_and_unknown_not_assigned_a_fake_0():
    assert percentage_shade("13", -10) == PALE
    assert percentage_shade("22", 120) == PL_BLUE
    assert percentage_shade("13", None) == NO_DATA
    assert percentage_shade("13", float("nan")) == NO_DATA
    assert percentage_shade("13", "x") == NO_DATA


def test_legend_explains_percentage_scale():
    html = legend_html("percentual")
    assert "Percentual de votos nominais" in html
    assert PT_RED in html and PL_BLUE in html
    assert "0–100%" in html
