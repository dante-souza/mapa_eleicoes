"""Seletores neutros, baseados apenas na disponibilidade efetiva dos dados."""
from __future__ import annotations


def round_label(round_number: int, available: list[int]) -> str:
    """Nao oculta o segundo turno; informa ausencia sem inventar resultados."""
    if round_number not in (1, 2):
        raise ValueError("O Atlas admite apenas os turnos 1 e 2")
    return (
        f"{round_number}º turno"
        if round_number in available
        else f"{round_number}º turno (sem dados)"
    )


def geometry_options(has_zone_polygons: bool) -> list[str]:
    """O limite municipal jamais sera oferecido como limite da zona."""
    return ["Município", "Zona eleitoral"] if has_zone_polygons else ["Município"]
