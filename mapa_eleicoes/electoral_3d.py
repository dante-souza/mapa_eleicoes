"""Camada 3D municipal: dados TSE e geografia IBGE, sem estimativas de votos."""
from __future__ import annotations

import json
import math
from pathlib import Path

import geopandas as gpd
import polars as pl

from mapa_eleicoes.geo_bridge import ibge_code
from mapa_eleicoes.party_colors import color_for_number
from mapa_eleicoes.results import br_number, region_results
from mapa_eleicoes.vote_sources import combine_sources

MODES = ("Margem de votos", "Margem percentual", "Votos do vencedor", "Votos do candidato")
COLUMNS = ["uf", "cd_municipio_tse", "municipio", "cargo", "turno",
           "numero", "candidato", "tipo_voto", "votos"]
KEYS = ["uf", "cd_municipio_tse"]


def load_votes(data: Path, year: int) -> tuple[pl.DataFrame, int]:
    sources = sorted((data / "serving" / str(year)).glob("votos_*.parquet"))
    if not sources:
        raise FileNotFoundError("Sem Parquets de serving para esse ano")
    return combine_sources({
        path.stem.removeprefix("votos_"): pl.read_parquet(path, columns=COLUMNS)
        for path in sources
    })


def load_reference(data: Path) -> pl.DataFrame:
    path = data / "reference" / "tse_ibge.csv"
    if not path.exists():
        raise FileNotFoundError("Correspondencia TSE/IBGE ausente")
    refs = pl.read_csv(path, infer_schema=False)
    if not set(KEYS + ["codigo_ibge"]).issubset(refs.columns):
        raise ValueError("De/para TSE/IBGE incompleto")
    refs = refs.select(KEYS + ["codigo_ibge"]).unique()
    collisions = refs.group_by(KEYS).len().filter(pl.col("len") > 1)
    if not collisions.is_empty():
        raise ValueError("De/para TSE/IBGE ambiguo")
    if not refs.filter(~pl.col("codigo_ibge").str.contains(r"^\d{7}$")).is_empty():
        raise ValueError("Codigo IBGE invalido no de/para")
    return refs


def load_geometry(data: Path) -> tuple[pl.DataFrame, dict]:
    path = data / "geo" / "municipios.geojson"
    if not path.exists():
        raise FileNotFoundError("Malha municipal IBGE ausente")
    shape = gpd.read_file(path)
    if shape.crs is None:
        raise ValueError("Malha municipal sem CRS")
    shape = shape.to_crs(4326)
    code_col = next((c for c in ("codigo_ibge", "CD_MUN", "CD_GEOCMU",
                                 "CD_MUN_IBGE", "code_muni", "id") if c in shape.columns), None)
    if code_col is None:
        raise ValueError("Malha municipal sem codigo IBGE")
    shape = shape.loc[shape.geometry.notna() & ~shape.geometry.is_empty].copy()
    shape["codigo_ibge"] = [ibge_code(value) for value in shape[code_col]]
    codes = list(shape["codigo_ibge"])
    if any(len(code) != 7 for code in codes) or len(set(codes)) != len(codes):
        raise ValueError("Malha com codigos IBGE invalidos ou duplicados")
    # representative_point e garantidamente interno; centroid pode cair fora.
    pts = shape.geometry.representative_point()
    points = pl.DataFrame([
        {"codigo_ibge": str(code), "longitude": float(p.x), "latitude": float(p.y)}
        for code, p in zip(codes, pts)
    ], schema={"codigo_ibge": pl.String, "longitude": pl.Float64, "latitude": pl.Float64})
    shape["uf_ibge"] = [code[:2] for code in codes]
    states = shape[["uf_ibge", "geometry"]].dissolve(by="uf_ibge")
    return points, json.loads(states.to_json(drop_id=True))


def municipal_totals(votes: pl.DataFrame, refs: pl.DataFrame,
                     candidate: str | None = None) -> pl.DataFrame:
    if votes.is_empty():
        return pl.DataFrame()
    if votes["cargo"].n_unique() != 1 or votes["turno"].n_unique() != 1:
        raise ValueError("Selecione apenas um cargo e turno")
    if not refs.group_by(KEYS).len().filter(pl.col("len") > 1).is_empty():
        raise ValueError("De/para ambiguo")
    ranking = region_results(votes, KEYS)
    if ranking.is_empty():
        return ranking
    names = votes.select(KEYS + ["municipio"]).sort("municipio").unique(
        subset=KEYS, keep="first"
    )
    out = ranking.join(names, on=KEYS, how="left", validate="1:1").join(
        refs.select(KEYS + ["codigo_ibge"]), on=KEYS, how="left", validate="m:1"
    ).with_columns((pl.col("votos_1") - pl.col("votos_2")).alias("margem_votos"))
    if candidate is not None:
        candidate_votes = votes.filter(
            (pl.col("tipo_voto") == "nominal") & (pl.col("numero") == candidate)
        ).group_by(KEYS).agg(pl.col("votos").sum().alias("votos_candidato"))
        out = out.join(candidate_votes, on=KEYS, how="left", validate="1:1").with_columns(
            pl.col("votos_candidato").fill_null(0))
    return out


def columns_for_map(totals: pl.DataFrame, points: pl.DataFrame, mode: str,
                    candidate: str | None = None, max_height: int = 160000) -> tuple[list[dict], dict]:
    if mode not in MODES or max_height <= 0:
        raise ValueError("Metrica ou altura invalida")
    if mode == "Votos do candidato" and candidate is None:
        raise ValueError("Selecione um candidato")
    if totals.is_empty():
        return [], {"sem_de_para": 0, "sem_geometria": 0, "p99": 0}
    mapped = totals.filter(pl.col("codigo_ibge").is_not_null() & (pl.col("codigo_ibge") != ""))
    located = mapped.join(points, on="codigo_ibge", how="inner", validate="m:1")
    metric_column = {
        "Margem de votos": "margem_votos",
        "Margem percentual": "margem_pp",
        "Votos do vencedor": "votos_1",
        "Votos do candidato": "votos_candidato",
    }[mode]
    if metric_column not in located.columns:
        raise ValueError("Metrica nao disponivel nos resultados")
    values = [float(v or 0) for v in located[metric_column].to_list()]
    positive = sorted(v for v in values if math.isfinite(v) and v > 0)
    p99 = positive[min(len(positive) - 1, int((len(positive) - 1) * 0.99))] if positive else 1.0
    output = []
    for record, value in zip(located.iter_rows(named=True), values):
        if not math.isfinite(value) or value < 0:
            continue
        color = (color_for_number(candidate) if mode == "Votos do candidato"
                 else "#a1a1aa" if record["empate"]
                 else color_for_number(record["numero_1"]))
        rgb = [int(color[i:i+2], 16) for i in (1, 3, 5)] + [235]
        output.append({
            "longitude": record["longitude"], "latitude": record["latitude"],
            "elevation": round(max_height * math.sqrt(min(value / p99, 1))),
            "color": rgb, "uf": record["uf"], "municipio": record["municipio"],
            "codigo_ibge": record["codigo_ibge"],
            "primeiro": record["candidato_1"] or "—",
            "segundo": record["candidato_2"] or "—",
            "votos_primeiro": br_number(record["votos_1"], 0),
            "votos_segundo": br_number(record["votos_2"], 0),
            "margem_votos": br_number(record["margem_votos"], 0),
            "margem_pp": br_number(record["margem_pp"], 2),
            "metrica": f"{br_number(value, 2)} p.p." if mode == "Margem percentual"
                       else f"{br_number(value, 0)} votos",
        })
    return output, {
        "sem_de_para": totals.height - mapped.height,
        "sem_geometria": mapped.height - located.height,
        "p99": p99,
    }
