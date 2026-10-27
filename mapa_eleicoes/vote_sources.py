"""Combina os Parquets de serving sem somar o mesmo voto duas vezes.

O arquivo nacional `votos_BR` (Presidente) e os arquivos por UF sao fontes
independentes. Se ambos trouxerem o mesmo (uf, cargo, turno), os votos
seriam contados em dobro. Regra: para cada (uf, cargo, turno) presente na
fonte nacional, a fonte nacional prevalece e as linhas estaduais
equivalentes sao descartadas (e contabilizadas para transparencia).
Combinacoes que so existem nos arquivos estaduais permanecem intactas.
"""
from __future__ import annotations

import polars as pl

NATIONAL = "BR"
OVERLAP_KEYS = ["uf", "cargo", "turno"]


def combine_sources(frames: dict[str, pl.DataFrame]) -> tuple[pl.DataFrame, int]:
    """Retorna (votos combinados, linhas estaduais descartadas por sobreposicao).

    `frames` mapeia o sufixo da fonte (BR, SP, ...) para o seu DataFrame.
    """
    present = {name: frame for name, frame in frames.items() if not frame.is_empty()}
    if not present:
        return pl.DataFrame(), 0
    national = present.get(NATIONAL)
    if national is None:
        return pl.concat(list(present.values()), how="vertical"), 0
    covered = national.select(OVERLAP_KEYS).unique()
    kept = [national]
    dropped = 0
    for name, frame in present.items():
        if name == NATIONAL:
            continue
        remaining = frame.join(covered, on=OVERLAP_KEYS, how="anti")
        dropped += frame.height - remaining.height
        kept.append(remaining)
    return pl.concat(kept, how="vertical"), dropped
