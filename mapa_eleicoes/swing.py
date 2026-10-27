"""Variação do saldo entre dois turnos por município ou zona do município.

Delta = (A_2T - B_2T) - (A_1T - B_1T).
Não infere transferência individual de eleitores. Usa somente votos nominais
do par; votos de outros candidatos não são redistribuídos.
"""
from __future__ import annotations

import polars as pl

REGION_KEYS = ["uf", "cd_municipio_tse"]
VOTE_TYPES = ["nominal", "legenda"]


def swing_results(
    votes: pl.DataFrame, *, level: str = "municipio",
    number_a: str = "13", number_b: str = "22",
) -> pl.DataFrame:
    """Calcula saldos, deltas e viradas de sinal; só compara regiões com 2 turnos.

    Uma ausência completa de dados de um turno nunca vira zero. Já um candidato
    com zero votos em um município/zona pode não ter linha nominal naquele
    recorte; recebe zero somente se o turno e ambos os candidatos estiverem
    presentes no conjunto de dados considerado.
    """
    if level not in ("municipio", "zona"):
        raise ValueError("Nível geográfico deve ser municipio ou zona.")
    if number_a == number_b:
        raise ValueError("Os números dos candidatos devem ser diferentes.")
    keys = REGION_KEYS + (["zona"] if level == "zona" else [])
    required = set(keys + ["municipio", "turno", "tipo_voto", "numero", "votos"])
    if not required.issubset(votes.columns):
        raise ValueError(f"Colunas eleitorais ausentes: {sorted(required - set(votes.columns))}")
    if votes.is_empty():
        return pl.DataFrame()

    selection = votes.filter(pl.col("turno").is_in([1, 2]))
    observed = set(
        selection.filter(
            (pl.col("tipo_voto") == "nominal")
            & pl.col("numero").is_in([number_a, number_b])
        ).select("turno", "numero").unique().iter_rows()
    )
    required_pairs = {(turno, numero) for turno in (1, 2) for numero in (number_a, number_b)}
    if not required_pairs.issubset(observed):
        missing = sorted(required_pairs - observed)
        raise ValueError(
            "Comparação indisponível: faltam candidatos/turnos nos registros "
            f"nominais oficiais deste recorte: {missing}."
        )

    # Exigimos evidência positiva dos votos válidos em CADA turno da região.
    # Isso evita que uma UF/município parcialmente carregado produza delta fictício.
    turnout = (
        selection.filter(pl.col("tipo_voto").is_in(VOTE_TYPES))
        .group_by(keys + ["turno"])
        .agg(pl.col("votos").sum().alias("validos"))
        .filter(pl.col("validos") > 0)
    )
    first = turnout.filter(pl.col("turno") == 1).select(
        keys + [pl.col("validos").alias("validos_1t")]
    )
    second = turnout.filter(pl.col("turno") == 2).select(
        keys + [pl.col("validos").alias("validos_2t")]
    )
    result = first.join(second, on=keys, how="inner")
    if result.is_empty():
        return pl.DataFrame()

    candidate_votes = (
        selection.filter(
            (pl.col("tipo_voto") == "nominal")
            & pl.col("numero").is_in([number_a, number_b])
        ).group_by(keys + ["turno", "numero"])
        .agg(pl.col("votos").sum().alias("votos"))
    )
    for label, numero in (("a", number_a), ("b", number_b)):
        for turno in (1, 2):
            name = f"votos_{label}_{turno}t"
            part = candidate_votes.filter(
                (pl.col("numero") == numero) & (pl.col("turno") == turno)
            ).select(keys + [pl.col("votos").alias(name)])
            result = result.join(part, on=keys, how="left").with_columns(
                pl.col(name).fill_null(0).cast(pl.Int64)
            )

    names = selection.select(keys + ["municipio"]).unique(subset=keys, keep="first")
    result = result.join(names, on=keys, how="left")
    result = result.with_columns(
        (pl.col("votos_a_1t") - pl.col("votos_b_1t")).alias("saldo_1t"),
        (pl.col("votos_a_2t") - pl.col("votos_b_2t")).alias("saldo_2t"),
        (pl.col("votos_a_2t") - pl.col("votos_a_1t")).alias("delta_a"),
        (pl.col("votos_b_2t") - pl.col("votos_b_1t")).alias("delta_b"),
    ).with_columns(
        (pl.col("saldo_2t") - pl.col("saldo_1t")).alias("delta"),
        pl.when((pl.col("saldo_1t") < 0) & (pl.col("saldo_2t") > 0))
        .then(pl.lit("Para A"))
        .when((pl.col("saldo_1t") > 0) & (pl.col("saldo_2t") < 0))
        .then(pl.lit("Para B"))
        .otherwise(pl.lit("Sem virada")).alias("virada"),
    ).with_columns(
        pl.when(pl.col("delta") > 0).then(pl.lit("A"))
        .when(pl.col("delta") < 0).then(pl.lit("B"))
        .otherwise(pl.lit("Neutro")).alias("favorece"),
    )
    return result.sort("delta", descending=True)


def state_swing_results(municipal: pl.DataFrame) -> pl.DataFrame:
    """Um delta por UF a partir de municípios com dois turnos comparáveis.

    Não usa contagem de setas ou média dos deltas: soma os votos/saldos antes
    de estabelecer a direção da mudança estadual. A cobertura comparável
    permanece explícita para não insinuar totalização estadual completa.
    """
    required = {"uf", "cd_municipio_tse", "saldo_1t", "saldo_2t",
                "delta", "delta_a", "delta_b"}
    if municipal.is_empty() or not required.issubset(municipal.columns):
        return pl.DataFrame()
    totals = municipal.group_by("uf").agg(
        pl.col("saldo_1t").sum(),
        pl.col("saldo_2t").sum(),
        pl.col("delta").sum(),
        pl.col("delta_a").sum(),
        pl.col("delta_b").sum(),
        pl.col("cd_municipio_tse").n_unique().alias("municipios_comparaveis"),
    )
    return totals.with_columns(
        pl.when((pl.col("saldo_1t") < 0) & (pl.col("saldo_2t") > 0))
        .then(pl.lit("Para A"))
        .when((pl.col("saldo_1t") > 0) & (pl.col("saldo_2t") < 0))
        .then(pl.lit("Para B"))
        .otherwise(pl.lit("Sem virada")).alias("virada"),
    ).sort("uf")
