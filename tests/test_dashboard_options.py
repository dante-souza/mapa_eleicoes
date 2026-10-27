"""Não esconder turnos e nunca fabricar limites cartográficos de zona."""
from __future__ import annotations

import pytest

from mapa_eleicoes.dashboard_options import geometry_options, round_label


def test_round_two_option_remains_visible_if_data_missing():
    assert round_label(1, [1]) == "1º turno"
    assert round_label(2, [1]) == "2º turno (sem dados)"
    assert round_label(2, [1, 2]) == "2º turno"


def test_round_options_reject_invalid_round():
    with pytest.raises(ValueError, match="1 e 2"):
        round_label(3, [1, 2])


def test_zone_polygons_only_offered_when_actual_zone_geometry_exists():
    assert geometry_options(False) == ["Município"]
    assert geometry_options(True) == ["Município", "Zona eleitoral"]
