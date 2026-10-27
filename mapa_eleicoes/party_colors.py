"""Cores eleitorais determinadas pelo numero do partido, nao pela ordenacao.

O CSV agregado do Atlas preserva NR_VOTAVEL (numero do candidato), mas nao
necessariamente SG_PARTIDO. Para candidatos nominais, o prefixo de dois
digitos de NR_VOTAVEL indica numero da legenda no pleito; nao usar o nome.
As cores aqui sao convencoes visuais do Atlas, nao cores oficiais do TSE.
"""
from __future__ import annotations

import hashlib

PT_RED = "#ff5555"       # PT / legenda 13 - Dracula red
PL_BLUE = "#3b82f6"      # PL / legenda 22 - azul bem distinguivel
UNKNOWN_COLOR = "#6272a4"

# Paleta reservada a demais legendas: nenhuma recebe o mesmo vermelho
# ou azul de PT e PL. Indice estavel independente do numero de votos.
OTHER_COLORS = (
    "#bd93f9", "#50fa7b", "#ffb86c", "#8be9fd",
    "#f1fa8c", "#ff79c6", "#94a3b8", "#c4b5fd",
)


def party_number(candidate_number: object) -> str | None:
    """Extrai numero da legenda para voto nominal; nunca infere pelo nome."""
    number = str(candidate_number).strip() if candidate_number is not None else ""
    if not number.isdecimal() or len(number) < 2:
        return None
    return number[:2]


def color_for_number(candidate_number: object) -> str:
    """Mantem PT/13 vermelho e PL/22 azul em qualquer ordenacao/filtro."""
    party = party_number(candidate_number)
    if party == "13":
        return PT_RED
    if party == "22":
        return PL_BLUE
    if party is None:
        return UNKNOWN_COLOR
    token = hashlib.sha256(party.encode("ascii")).digest()
    return OTHER_COLORS[int.from_bytes(token[:2], "big") % len(OTHER_COLORS)]
