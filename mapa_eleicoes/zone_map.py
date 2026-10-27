"""Camadas Folium de areas APROXIMADAS de zona eleitoral.

Geometria: mapa_eleicoes.zone_geometry (setores IBGE 2022 + locais TSE).
Duas camadas, mesmas cores do mapa municipal (lider + margem em p.p.; no
modo de candidato, % dos validos):

- zone_layer: zonas DENTRO da cidade, votos por (uf, municipio TSE, zona).
  Municipio com uma unica zona nao ganha camada: repetiria o municipio.
- district_layer: a zona inteira (uf, zona), que pode abranger varios
  municipios; base do detalhamento "Zona eleitoral (aproximada)".
"""
from __future__ import annotations

import json
from html import escape
from pathlib import Path

import folium
import geopandas as gpd
import polars as pl
from shapely.geometry import Point

from mapa_eleicoes.geo_bridge import add_properties
from mapa_eleicoes.map_navigation import valid_position
from mapa_eleicoes.results import br_number, region_results
from mapa_eleicoes.vote_gradients import NO_DATA, margin_shade, percentage_shade
from mapa_eleicoes.zone_geometry import ZONE_KEYS, district_file, zone_file
from mapa_eleicoes.zone_names import zone_label

MAX_ZONE_AREAS = 900


DISTRICT_KEYS = ["uf", "zona"]
# Nome = bairro (zona na cidade) ou municipio com mais secoes: zone_names.
APPROXIMATE_NOTE = "Área aproximada e nome derivado (IBGE 2022 + TSE)"
Labels = tuple[dict[str, str], dict[str, str]]  # ver zone_names.zone_labels


def zone_areas_available(root: Path) -> bool:
    return any((root / "geo" / "zonas").glob("zonas_municipio_*.geojson"))


def districts_available(root: Path, uf: str | None = None) -> bool:
    folder = root / "geo" / "zonas"
    if uf is None:
        return any(folder.glob("zonas_uf_*.geojson"))
    return district_file(root, uf).is_file()


def _read(path: Path) -> gpd.GeoDataFrame | None:
    if not path.is_file():
        return None
    areas = gpd.read_file(path)
    if areas.crs is None:
        raise ValueError("Areas de zona sem CRS")
    return areas.to_crs(4326)


def load_zone_areas(root: Path, uf: str) -> gpd.GeoDataFrame | None:
    return _read(zone_file(root, uf))


def load_districts(root: Path, uf: str) -> gpd.GeoDataFrame | None:
    return _read(district_file(root, uf))


def _results(
    votes: pl.DataFrame, keys: list[str], selected_number: str | None,
) -> pl.DataFrame:
    if votes.is_empty() or not set(keys) <= set(votes.columns):
        return pl.DataFrame()
    results = region_results(votes, keys)
    if results.is_empty():
        return results
    results = results.with_columns(
        pl.format(":".join("{}" for _ in keys), *[pl.col(k) for k in keys]).alias("map_id")
    )
    if selected_number is not None:
        chosen = (
            votes.filter((pl.col("tipo_voto") == "nominal")
                         & (pl.col("numero") == selected_number))
            .group_by(keys).agg(pl.col("votos").sum().alias("votos_sel"))
        )
        results = results.join(chosen, on=keys, how="left").with_columns(
            pl.when(pl.col("total_validos") > 0)
            .then(100.0 * pl.col("votos_sel").fill_null(0) / pl.col("total_validos"))
            .otherwise(None).alias("destaque")
        )
    return results


def zone_results(votes: pl.DataFrame, selected_number: str | None = None) -> pl.DataFrame:
    """1o/2o/margem por zona do municipio + % do candidato selecionado."""
    return _results(votes, ZONE_KEYS, selected_number)


def district_results(votes: pl.DataFrame, selected_number: str | None = None) -> pl.DataFrame:
    """1o/2o/margem pela zona inteira (uf, zona), somando todos os municipios."""
    return _results(votes, DISTRICT_KEYS, selected_number)


def _line(rank: int, name: object, pct: object, votes: object) -> str:
    if not isinstance(name, str) or not name:
        return "—"
    return f"{rank}º {escape(name)} — {br_number(pct)}% · {br_number(votes, 0)} votos"


def _result_layer(
    areas: gpd.GeoDataFrame, results: pl.DataFrame, titles: list[str], *,
    layer_name: str, selected_number: str | None, highlight_zone: int | None,
    pane: str | None, extra: dict[str, tuple[str, list[str]]] | None = None,
    fill_opacity: float = 1.0,
) -> folium.FeatureGroup:
    """Poligonos coloridos + tooltip comum as duas camadas de zona."""
    defaults = {
        "candidato_1": None, "numero_1": "", "votos_1": 0, "pct_1": None,
        "candidato_2": None, "votos_2": 0, "pct_2": None,
        "margem_pp": None, "empate": False, "destaque": None,
    }
    joined = add_properties(areas, results, defaults)
    display = joined[["map_id", "geometry"]].copy()
    display["titulo"] = titles
    fields, aliases = ["titulo"], [""]
    for column, (alias, values) in (extra or {}).items():
        display[column] = values
        fields.append(column)
        aliases.append(alias)
    display["aviso"] = [APPROXIMATE_NOTE] * len(joined)
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
    fields += ["aviso", "primeiro", "segundo", "margem"]
    aliases += ["", "Mais votado", "2º colocado", "Diferença"]
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
    chosen = {
        key for key, zona in zip(joined["map_id"], joined["zona"])
        if highlight_zone is not None and int(zona) == int(highlight_zone)
    }

    def style(feature):
        key = feature["properties"]["map_id"]
        base = {
            "fillColor": color_by_key.get(key, NO_DATA),
            "fillOpacity": fill_opacity, "color": "#f8f8f2", "weight": 0.8,
            "dashArray": "4 3",
        }
        if chosen:
            # Zona escolhida no seletor: contorno cheio; as demais esmaecem.
            if key in chosen:
                base.update({"weight": 3.2, "color": "#ffffff", "dashArray": None})
            else:
                base.update({"fillOpacity": 0.45})
        return base

    geojson = json.loads(display.to_json(drop_id=True))
    layer = folium.FeatureGroup(name=layer_name)
    folium.GeoJson(
        geojson,
        name=layer_name,
        style_function=style,
        highlight_function=lambda _: {"weight": 2.4, "color": "#ffffff"},
        tooltip=folium.GeoJsonTooltip(fields=fields, aliases=aliases, sticky=False),
        **({"pane": pane} if pane else {}),
    ).add_to(layer)
    return layer


def zone_layer(
    areas: gpd.GeoDataFrame,
    votes: pl.DataFrame,
    *,
    names: dict[str, str] | None = None,  # "UF:codigo TSE" -> nome
    selected_number: str | None = None,
    highlight_zone: int | None = None,
    pane: str | None = None,
    labels: Labels | None = None,
) -> tuple[folium.FeatureGroup | None, int]:
    """Zonas dentro das cidades com mais de uma zona; (None, 0) sem dados."""
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
    names = names or {}
    neighborhood, seat = labels or ({}, {})
    titles = []
    for zona, tse, uf in zip(areas["zona"], areas["cd_municipio_tse"], areas["uf"]):
        city = escape(names.get(f"{uf}:{tse}", str(tse)))
        name = zone_label(uf, zona, tse, neighborhood, seat, names)
        head = f"Zona {int(zona)} · {escape(name)}" if name else f"Zona {int(zona)}"
        titles.append(f"{head} — {city} ({escape(str(uf))})")
    layer = _result_layer(
        areas, results, titles, layer_name="Zonas eleitorais (área aproximada)",
        selected_number=selected_number, highlight_zone=highlight_zone, pane=pane,
    )
    return layer, len(areas)


def _city_list(codes: object, uf: str, names: dict[str, str], limit: int = 4) -> str:
    items = [code for code in str(codes or "").split(",") if code]
    labels = [escape(names.get(f"{uf}:{code}", code)) for code in items[:limit]]
    rest = len(items) - limit
    return ", ".join(labels) + (f" e mais {rest}" if rest > 0 else "")


def district_layer(
    districts: gpd.GeoDataFrame,
    votes: pl.DataFrame,
    *,
    names: dict[str, str] | None = None,  # "UF:codigo TSE" -> nome
    selected_number: str | None = None,
    highlight_zone: int | None = None,
    pane: str | None = None,
    labels: Labels | None = None,
) -> tuple[folium.FeatureGroup | None, int]:
    """Zona inteira (uf, zona), atravessando municipios; (None, 0) sem dados."""
    if districts is None or districts.empty:
        return None, 0
    results = district_results(votes, selected_number)
    if results.is_empty():
        return None, 0
    keys = set(results.get_column("map_id").to_list())
    districts = districts.loc[[str(key) in keys for key in districts["map_id"]]]
    if districts.empty:
        return None, 0
    names = names or {}
    neighborhood, seat = labels or ({}, {})
    titles = []
    for zona, uf in zip(districts["zona"], districts["uf"]):
        name = zone_label(uf, zona, None, neighborhood, seat, names)
        head = f"Zona {int(zona)} · {escape(name)}" if name else f"Zona {int(zona)}"
        titles.append(f"{head} ({escape(str(uf))})")
    cities = [
        _city_list(codes, str(uf), names)
        for codes, uf in zip(districts["municipios_tse"], districts["uf"])
    ]
    layer = _result_layer(
        districts, results, titles, layer_name="Zonas eleitorais (área aproximada)",
        selected_number=selected_number, highlight_zone=highlight_zone, pane=pane,
        extra={"municipios": ("Municípios", cities)},
        # Camada principal deste modo: opaca, sem o mosaico municipal por baixo.
        fill_opacity=1.0,
    )
    return layer, len(districts)


def zone_at(districts: gpd.GeoDataFrame | None, position: dict | None) -> int | None:
    """Numero da zona (area aproximada) sob o clique."""
    point = valid_position(position)
    if districts is None or districts.empty or point is None:
        return None
    target = Point(point[1], point[0])
    for idx in districts.sindex.query(target, predicate="intersects"):
        row = districts.iloc[int(idx)]
        if row.geometry is not None and row.geometry.covers(target):
            return int(row["zona"])
    return None
