"""Cores estáveis por legenda, inclusive sob alteração da ordem/ranking."""
from __future__ import annotations

from mapa_eleicoes.party_colors import (
    PT_RED, PL_BLUE, UNKNOWN_COLOR,
    OTHER_COLORS, color_for_number, party_number,
)


def test_pt_13_red_in_all_nominal_ballot_lengths():
    assert party_number("13") == "13"
    assert party_number("130") == "13"
    assert party_number("1300") == "13"
    assert party_number("13000") == "13"
    assert color_for_number("13") == PT_RED
    assert color_for_number("130") == PT_RED
    assert color_for_number("13000") == PT_RED


def test_pl_22_blue_in_all_nominal_ballot_lengths():
    assert party_number("22") == "22"
    assert color_for_number("22") == PL_BLUE
    assert color_for_number("220") == PL_BLUE
    assert color_for_number("22000") == PL_BLUE


def test_other_parties_never_use_pt_red_or_pl_blue():
    for number in ("10", "11", "12", "15", "20", "40", "45", "50", "55", "77"):
        color = color_for_number(number)
        assert color in OTHER_COLORS
        assert color not in (PT_RED, PL_BLUE)
        assert color_for_number(number) == color_for_number(number + "000")


def test_unknown_candidate_does_not_get_party_color():
    for number in (None, "", "x", "1", "-13", "13A"):
        assert party_number(number) is None
        assert color_for_number(number) == UNKNOWN_COLOR
