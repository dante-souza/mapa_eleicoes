"""Camada Folium de areas APROXIMADAS de zona eleitoral dentro da cidade.

Geometria: mapa_eleicoes.zone_geometry (setores IBGE 2022 + locais TSE).
Votos: Parquets de serving por (uf, municipio TSE, zona). Mesmas cores do
mapa municipal: lider + margem em p.p.; no modo de candidato, % valido.
Municipio com uma unica zona nao ganha camada: ela repetiria o municipio.
"""
from __future__ import annotations

import json
from html import escape
from pathlib import Path

import folium
import geopandas as gpd
import polars as pl

from mapa_eleicoes.geo_bridge import add_properties
from mapa_eleicoes.results import br_number, region_results
from mapa_eleicoes.vote_gradients import NO_DATA, margin_shade, percentage_shade
from mapa_eleicoes.zone_geometry import ZONE_KEYS, zone_file

MAX_ZONE_AREAS = 900


def zone_areas_available(root: Path) -> bool:
    return any((root / "geo" / "zonas").glob("zonas_municipio_*.geojson"))


def load_zone_areas(root: Path, uf: str) -> gpd.GeoDataFrame | None:
    path = zone_file(root, uf)
    if not path.is_file():
        return None
    areas = gpd.read_file(path)
    if areas.crs is None:
        raise ValueError("Areas de zona sem CRS")
    return areas.to_crs(4326)


def zone_results(votes: pl.DataFrame, selected_number: str | None = None) -> pl.DataFrame:
    """1o/2o/margem por zona do municipio + % do candidato selecionado."""
    if votes.is_empty() or not set(ZONE_KEYS) <= set(votes.columns):
        return pl.DataFrame()
    results = region_results(votes, ZONE_KEYS)
    if results.is_empty():
        return results
    results = results.with_columns(
        pl.format("{}:{}:{}", pl.col("uf"), pl.col("cd_municipio_tse"),
                  pl.col("zona")).alias("map_id")
    )
    if selected_number is not None:
        chosen = (
            votes.filter((pl.col("tipo_voto") == "nominal")
                         & (pl.col("numero") == selected_number))
            .group_by(ZONE_KEYS).agg(pl.col("votos").sum().alias("votos_sel"))
        )
        results = results.join(chosen, on=ZONE_KEYS, how="left").with_columns(
            pl.when(pl.col("total_validos") > 0)
            .then(100.0 * pl.col("votos_sel").fill_null(0) / pl.col("total_validos"))
            .otherwise(None).alias("destaque")
        )
    return results


def _line(rank: int, name: object, pct: object, votes: object) -> str:
    if not isinstance(name, str) or not name:
        return "—"
    return f"{rank}º {escape(name)} — {br_number(pct)}% · {br_number(votes, 0)} votos"


def zone_layer(
    areas: gpd.GeoDataFrame,
    votes: pl.DataFrame,
    *,
    names: dict[str, str] | None = None,  # "UF:codigo TSE" -> nome
    selected_number: str | None = None,
) -> tuple[folium.FeatureGroup | None, int]:
    """FeatureGroup com zonas coloridas e tooltip; (None, 0) sem dados."""
    if areas is None or areas.empty:
        return None, 0
    results = zone_results(votes, selected_number)
    if results.is_empty():
        return None, 0
    keys = set(results.get_column("map_id").to_list())
    multi = [
        int(n) > 1 and str(key) in keys
        for n, key in zip(areas["n_zonas_municipio"], areas["map_id"])
    ]
    areas = areas.loc[multi]
    if areas.empty:
        return None, 0
    areas = areas.iloc[:MAX_ZONE_AREAS]
    defaults = {
        "candidato_1": None, "numero_1": "", "votos_1": 0, "pct_1": None,
        "candidato_2": None, "votos_2": 0, "pct_2": None,
        "margem_pp": None, "empate": False, "destaque": None,
    }
    joined = add_properties(areas, results, defaults)
    names = names or {}
    display = joined[["map_id", "geometry"]].copy()
    display["titulo"] = [
        f"Zona {int(zona)} · {escape(names.get(f'{uf}:{tse}', str(tse)))} ({escape(str(uf))})"
        for zona, tse, uf in zip(joined["zona"], joined["cd_municipio_tse"], joined["uf"])
    ]
    display["aviso"] = ["Área aproximada (setores IBGE 2022 + locais TSE)"] * len(joined)
    display["primeiro"] = [
        _line(1, n, p, v) for n, p, v in
        zip(joined["candidato_1"], joined["pct_1"], joined["votos_1"])
    ]
    display["segundo"] = [
        _line(2, n, p, v) for n, p, v in
        zip(joined["candidato_2"], joined["pct_2"], joined["votos_2"])
    ]
    display["margem"] = [
        "Empate" if tie else (
            "—" if br_number(m, 1) == "—" else f"{br_number(m, 1)} p.p."
        )
        for tie, m in zip(joined["empate"], joined["margem_pp"])
    ]
    fields = ["titulo", "aviso", "primeiro", "segundo", "margem"]
    aliases = ["", "", "Mais votado", "2º colocado", "Diferença"]
    if selected_number is not None:
        display["destaque"] = [f"{br_number(v)}%" for v in joined["destaque"]]
        fields.append("destaque")
        aliases.append(f"Número {escape(str(selected_number))} (% válidos)")
        colors = [percentage_shade(selected_number, v) for v in joined["destaque"]]
    else:
        colors = [
            margin_shade(number, margin, bool(tie)) if isinstance(name, str) else NO_DATA
            for number, margin, tie, name in zip(
                joined["numero_1"], joined["margem_pp"],
                joined["empate"], joined["candidato_1"],
            )
        ]
    color_by_key = dict(zip(joined["map_id"], colors))
    geojson = json.loads(display.to_json(drop_id=True))
    layer = folium.FeatureGroup(name="Zonas eleitorais (área aproximada)")
    folium.GeoJson(
        geojson,
        name="Zonas eleitorais (área aproximada)",
        style_function=lambda feature: {
            "fillColor": color_by_key.get(feature["properties"]["map_id"], NO_DATA),
            "fillOpacity": 0.9, "color": "#f8f8f2", "weight": 0.8,
            "dashArray": "4 3",
        },
        highlight_function=lambda _: {"weight": 2.2, "color": "#ffffff"},
        tooltip=folium.GeoJsonTooltip(fields=fields, aliases=aliases, sticky=False),
    ).add_to(layer)
    return layer, len(display)
