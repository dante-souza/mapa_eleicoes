"""Resultado por recorte geografico: 1o, 2o, margem e empate.

Somente Polars. Denominador = votos validos (nominais + legenda), como na
totalizacao oficial; brancos e nulos nao entram. O ranking considera apenas
candidatos (votos nominais): voto de legenda nao e candidato.
"""
from __future__ import annotations

import polars as pl

VALID_TYPES = ("nominal", "legenda")
# Classes de margem (p.p.) entre 1o e 2o colocados, no estilo de mapa de
# apuracao: limites inferiores inclusivos.
# Mesmas classes do mapa de apuracao do g1: 0-5, 5-20 e acima de 20 p.p.
MARGIN_BREAKS = (5.0, 20.0)
MARGIN_LABELS = ("0 a 5 p.p.", "5 a 20 p.p.", "acima de 20 p.p.")

RESULT_COLUMNS = [
    "numero_1", "candidato_1", "votos_1", "pct_1",
    "numero_2", "candidato_2", "votos_2", "pct_2",
    "margem_pp", "empate", "total_validos",
]


def region_results(frame: pl.DataFrame, keys: list[str]) -> pl.DataFrame:
    """Uma linha por recorte com os dois mais votados e a margem.

    Recorte com um unico candidato: 2o colocado vazio, margem = pct_1.
    Empate no topo e explicito (empate=True); a ordem por numero fica
    apenas para estabilidade de exibicao.
    """
    if frame.is_empty() or not set(keys) <= set(frame.columns):
        return pl.DataFrame()
    totals = (
        frame.filter(pl.col("tipo_voto").is_in(VALID_TYPES))
        .group_by(keys).agg(pl.col("votos").sum().alias("total_validos"))
    )
    ranked = (
        frame.filter(pl.col("tipo_voto") == "nominal")
        .group_by(keys + ["numero", "candidato"])
        .agg(pl.col("votos").sum())
        .sort(keys + ["votos", "numero"],
              descending=[False] * len(keys) + [True, False])
        .with_columns(pl.int_range(pl.len()).over(keys).alias("posicao"))
        .filter(pl.col("posicao") < 2)
    )
    if ranked.is_empty():
        return pl.DataFrame()
    first = ranked.filter(pl.col("posicao") == 0).select(
        keys + [pl.col("numero").alias("numero_1"),
                pl.col("candidato").alias("candidato_1"),
                pl.col("votos").alias("votos_1")]
    )
    second = ranked.filter(pl.col("posicao") == 1).select(
        keys + [pl.col("numero").alias("numero_2"),
                pl.col("candidato").alias("candidato_2"),
                pl.col("votos").alias("votos_2")]
    )
    result = (
        first.join(second, on=keys, how="left")
        .join(totals, on=keys, how="left")
        .with_columns(
            pl.col("votos_2").fill_null(0),
            pl.col("total_validos").fill_null(0),
        )
    )
    share = lambda column: (  # noqa: E731 - expressao curta reaproveitada
        pl.when(pl.col("total_validos") > 0)
        .then(100.0 * pl.col(column) / pl.col("total_validos"))
        .otherwise(None)
    )
    return result.with_columns(
        share("votos_1").alias("pct_1"),
        share("votos_2").alias("pct_2"),
    ).with_columns(
        (pl.col("pct_1") - pl.col("pct_2").fill_null(0.0)).alias("margem_pp"),
        ((pl.col("votos_1") == pl.col("votos_2")) & (pl.col("votos_1") > 0))
        .alias("empate"),
    ).select(keys + RESULT_COLUMNS)


def margin_class(margin: object) -> int | None:
    """0..2 conforme MARGIN_BREAKS; None quando nao ha dado."""
    try:
        value = float(margin)
    except (TypeError, ValueError):
        return None
    if value != value:
        return None
    return sum(value >= limit for limit in MARGIN_BREAKS)


def br_number(value: object, decimals: int = 2) -> str:
    """Formato brasileiro: 12.345,67."""
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number != number:
        return "—"
    text = f"{number:,.{decimals}f}"
    return text.replace(",", "§").replace(".", ",").replace("§", ".")
