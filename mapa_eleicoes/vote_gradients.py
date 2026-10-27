"""Escalas continuas para mapas de resultado eleitoral.

A cor base depende do numero da legenda; a intensidade reflete a
porcentagem de votos nominais no recorte, nao tamanho da populacao.
Cores convencionais, sem inferencia sobre preferencias individuais.
"""
from __future__ import annotations

from mapa_eleicoes.party_colors import color_for_number

PALE = "#e9e6ef"
NO_DATA = "#44475a"


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    if len(color) != 6:
        raise ValueError("Cor precisa ter seis digitos hexadecimais")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _blend(a: str, b: str, strength: float) -> str:
    first, second = _hex_to_rgb(a), _hex_to_rgb(b)
    v = max(0.0, min(1.0, float(strength)))
    return "#" + "".join(
        f"{round(x * (1.0 - v) + y * v):02x}"
        for x, y in zip(first, second)
    )


def percentage_shade(candidate_number: object, percent: object) -> str:
    """0% quase neutro; 100% cor forte da legenda.

    NULL/NaN nao sao convertidos em zero aparente.
    """
    if percent is None:
        return NO_DATA
    try:
        fraction = float(percent) / 100.0
    except (ValueError, TypeError):
        return NO_DATA
    if fraction != fraction:
        return NO_DATA
    return _blend(PALE, color_for_number(candidate_number), fraction)


def legend_html(mode: str) -> str:
    """Legenda visivel no Folium, sem API de mapa externo."""
    descriptor = (
        "Percentual de votos nominais"
        if mode == "percentual" else "Diferença para o segundo colocado (p.p.)"
    )
    from mapa_eleicoes.party_colors import PT_RED, PL_BLUE
    def gradient(color: str) -> str:
        return f"linear-gradient(90deg, {PALE}, {color})"
    rows = "".join(
        '<div style="display:flex;align-items:center;gap:8px;margin-top:5px">'
        f'<span style="width:28px">{label}</span>'
        f'<span style="height:12px;width:126px;border-radius:3px;background:{gradient(color)}"></span>'
        '<span style="font-size:10px">0–100%</span></div>'
        for label,color in (("13",PT_RED),("22",PL_BLUE))
    )
    return (
        '<div style="position:fixed;z-index:9999;right:15px;bottom:28px;'
        'background:rgba(40,42,54,.94);border:1px solid #6272a4;'
        'border-radius:8px;color:#f8f8f2;padding:10px;font:12px sans-serif">'
        f'<b>{descriptor}</b>{rows}'
        '<div style="font-size:10px;margin-top:6px">Demais legendas: cor por número eleitoral</div>'
        '</div>'
    )
