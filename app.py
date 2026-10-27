"""Atlas Eleitoral. O unico ponto de entrada operacional e make run.

Polars: dados/votos/joins/agrupamentos. GeoPandas: exclusivamente geometria.
Nao converter Arrow/Polars para pandas nem fazer GeoDataFrame.merge com Polars.
"""
from __future__ import annotations

import json
from html import escape
from pathlib import Path

import folium
import geopandas as gpd
import polars as pl
import streamlit as st

from mapa_eleicoes.geo_bridge import add_properties, ibge_code, zone_code
from mapa_eleicoes.map_tiles import atlas_map
from mapa_eleicoes.office_catalog import available_offices, available_turns, preferred_office
from mapa_eleicoes.dashboard_options import round_label, geometry_options
from mapa_eleicoes.vote_gradients import percentage_shade, margin_shade, legend_html
from mapa_eleicoes.results import region_results, br_number
from mapa_eleicoes.vote_sources import combine_sources
from mapa_eleicoes.interactive_map import PENDING_ZONE, ZONE_DETAIL, render_explorer
from mapa_eleicoes.map_focus import CityFocus, context_layer
from mapa_eleicoes.zone_geometry import UF_PREFIX
from mapa_eleicoes.zone_map import districts_available

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
TEXT_COLUMNS = ["uf", "cd_municipio_tse", "municipio", "numero",
                "candidato", "cargo", "tipo_voto"]

st.set_page_config(page_title="Atlas Eleitoral", page_icon="🗳️", layout="wide")
st.markdown("""<style>
[data-testid="stAppViewContainer"] {background:#191923;color:#f8f8f2}
[data-testid="stSidebar"] {background:#252536}
[data-testid="stMetric"] {background:#282a36;border:1px solid #44475a;border-radius:10px;padding:14px}
.block-container {max-width:1750px;padding-top:1.2rem}
</style>""", unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def load_votes(year: int) -> tuple[pl.DataFrame, int]:
    """Consome exclusivamente dados finais Parquet gerados antes da interface.

    Fonte nacional (BR) e estaduais nunca somam o mesmo (uf, cargo, turno).
    """
    folder = DATA / "serving" / str(year)
    files = sorted(folder.glob("votos_*.parquet"))
    frames = {
        path.stem.removeprefix("votos_"): pl.read_parquet(path)
        for path in files
    }
    return combine_sources(frames)


@st.cache_data(show_spinner=False)
def load_catalog(year: int) -> dict:
    """O catalogo explica quais fontes e turnos estao materializados."""
    path = DATA / "serving" / str(year) / "catalog.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


@st.cache_data(show_spinner=False)
def load_shape(level: str) -> gpd.GeoDataFrame | None:
    filename = "zonas.geojson" if level == "Zona eleitoral" else "municipios.geojson"
    path = DATA / "geo" / filename
    if not path.exists():
        return None
    shape = gpd.read_file(path)
    if shape.crs is None:
        raise ValueError("GeoJSON sem CRS")
    return shape.to_crs(4326)


@st.cache_data(show_spinner=False)
def crosswalk() -> pl.DataFrame | None:
    path = DATA / "reference" / "tse_ibge.csv"
    if not path.exists():
        return None
    return pl.read_csv(path, infer_schema=False).with_columns(pl.all().fill_null(""))


def field(geometry: gpd.GeoDataFrame, candidates: list[str]) -> str | None:
    return next((name for name in candidates if name in geometry.columns), None)


def attach_ibge(votes: pl.DataFrame) -> pl.DataFrame:
    """map_id = codigo IBGE do municipio, pelo de/para TSE->IBGE (nunca nome)."""
    correspondence = crosswalk()
    if correspondence is None:
        raise ValueError("A correspondencia territorial TSE/IBGE nao esta disponivel.")
    keys = ["uf", "cd_municipio_tse", "codigo_ibge"]
    missing = set(keys) - set(correspondence.columns)
    if missing:
        raise ValueError(f"De/para incompleto: {missing}")
    unique = correspondence.select(keys).unique()
    conflicts = unique.group_by(["uf", "cd_municipio_tse"]).len().filter(pl.col("len") > 1)
    if not conflicts.is_empty():
        raise ValueError("De/para ambiguo: um municipio TSE tem mais de um codigo IBGE.")
    return votes.join(unique, on=["uf", "cd_municipio_tse"], how="left",
                      validate="m:1").with_columns(
                          pl.col("codigo_ibge").fill_null("").alias("map_id"))


def shape_for_votes(geometry: gpd.GeoDataFrame, votes: pl.DataFrame, level: str):
    """Atribui chaves geograficas sem cruzar series Polars com GeoPandas."""
    geometry = geometry.copy()
    if level == "Zona eleitoral":
        uf_col = field(geometry, ["UF", "uf", "SG_UF", "sg_uf"])
        zone_col = field(geometry, ["NR_ZONA", "nr_zona", "zona", "ZONA"])
        if not uf_col or not zone_col:
            raise ValueError("Malha de zonas precisa de UF e NR_ZONA.")
        geometry["map_id"] = [
            zone_code(uf, zone) for uf, zone in
            zip(geometry[uf_col], geometry[zone_col])
        ]
        votes = votes.with_columns(pl.format("{}:{}", pl.col("uf"), pl.col("zona")).alias("map_id"))
    else:
        votes = attach_ibge(votes)
        code_col = field(geometry, ["CD_MUN", "CD_GEOCMU", "codarea",
                                    "codigo_ibge", "code_muni", "id", "CD_MUN_IBGE"])
        if not code_col:
            raise ValueError("Malha municipal sem codigo IBGE de 7 digitos.")
        geometry["map_id"] = [ibge_code(value) for value in geometry[code_col]]
    return geometry, votes


def _place_line(rank: int, name: object, pct: object, votes: object) -> str:
    """Linha de tooltip: '1º NOME — 80,80% · 12.345 votos'. Texto escapado,
    pois o tooltip do Leaflet e inserido como HTML."""
    if not name:
        return "—"
    return (
        f"{rank}º {escape(str(name))} — {br_number(pct)}% · "
        f"{br_number(votes, 0)} votos"
    )


def draw_map(geometry: gpd.GeoDataFrame, data: pl.DataFrame, mode: str,
             selected: str | None, level: str, *,
             year: int, uf: str, cargo: str, turno: int,
             municipality: str, zone: int | str,
             detail: str, section_ready: bool,
             zone_votes: pl.DataFrame | None = None,
             district_votes: pl.DataFrame | None = None):
    winners = region_results(data, ["map_id"])
    if winners.is_empty():
        st.info("Sem votos nominais para gerar mapa.")
        return
    # Cor do partido extraida de NR_VOTAVEL. Nunca depende do ranking
    # momentaneo de votos, do nome ou da ordem retornada pelo Polars.
    selected_number = None
    if mode == "Votação de candidato" and selected:
        numbers = (
            data.filter(
                (pl.col("tipo_voto") == "nominal")
                & (pl.col("candidato") == selected)
            )
            .group_by("numero").agg(pl.col("votos").sum())
            .sort(["votos", "numero"], descending=[True, False])
        )
        if not numbers.is_empty():
            selected_number = numbers.get_column("numero")[0]
        candidate_votes = (
            data.filter(
                (pl.col("tipo_voto") == "nominal")
                & (pl.col("candidato") == selected)
                & (pl.col("numero") == selected_number)
            )
            .group_by("map_id").agg(pl.col("votos").sum().alias("votos_candidato"))
        )
        winners = winners.join(candidate_votes, on="map_id", how="left").with_columns(
            pl.col("votos_candidato").fill_null(0),
        ).with_columns(
            pl.when(pl.col("total_validos") > 0)
            .then(100.0 * pl.col("votos_candidato") / pl.col("total_validos"))
            .otherwise(None).alias("destaque")
        )

    keys = set(data.get_column("map_id").drop_nulls().to_list())
    all_geometry = geometry
    geometry = geometry.loc[geometry["map_id"].isin(keys) & geometry.geometry.notna()].copy()
    if geometry.empty:
        st.warning("Nao foi possivel associar os votos a malha. Revise as chaves.")
        return
    # Fronteira estavel: conversao Polars -> registros Python tipados (nao DataFrame pandas).
    attributes = {
        "candidato_1": None, "numero_1": "", "votos_1": 0, "pct_1": None,
        "candidato_2": None, "votos_2": 0, "pct_2": None,
        "margem_pp": None, "empate": False,
    }
    if mode == "Votação de candidato" and selected:
        attributes["destaque"] = 0.0
    joined = add_properties(geometry, winners, attributes)
    display = joined[["map_id", "geometry"]].copy()
    # Nomes oficiais do CSV TSE sao apenas exibidos como rotulos.
    # O cruzamento cartografico continua EXCLUSIVAMENTE por geocodigos.
    names = (
        data.select(["map_id", "municipio"])
        .filter(pl.col("municipio").is_not_null() & (pl.col("municipio") != ""))
        .unique(subset=["map_id"], keep="first")
    )
    name_by_code = {
        str(item["map_id"]): item["municipio"]
        for item in names.iter_rows(named=True)
    } if level == "Município" else {}
    display["nome_tooltip"] = [
        str(name_by_code.get(str(value), value)) for value in joined["map_id"]
    ]
    display["codigo_tooltip"] = [str(value) for value in joined["map_id"]]
    display["primeiro"] = [
        _place_line(1, name, pct, votes) if name else "Sem dados"
        for name, pct, votes in zip(joined["candidato_1"], joined["pct_1"], joined["votos_1"])
    ]
    display["segundo"] = [
        _place_line(2, name, pct, votes)
        for name, pct, votes in zip(joined["candidato_2"], joined["pct_2"], joined["votos_2"])
    ]
    display["margem"] = [
        "Empate" if tie else (
            "—" if br_number(margin, 1) == "—" else f"{br_number(margin, 1)} p.p."
        )
        for tie, margin in zip(joined["empate"], joined["margem_pp"])
    ]
    if "destaque" in attributes:
        display["destaque"] = [
            f"{br_number(value)}%" for value in joined["destaque"]
        ]
    geojson = json.loads(display.to_json(drop_id=True))
    color_by_key = dict(zip(joined["map_id"], [
        margin_shade(number, margin, bool(tie)) if name else "#44475a"
        for number, margin, tie, name in zip(
            joined["numero_1"], joined["margem_pp"],
            joined["empate"], joined["candidato_1"],
        )
    ]))
    highlight = dict(zip(joined["map_id"], [
        float(value or 0) for value in joined.get("destaque", [0] * len(joined))
    ]))
    centroid = geometry.geometry.union_all().representative_point()
    bounds = geometry.total_bounds
    map_view = atlas_map([float(centroid.y), float(centroid.x)])

    def style(feature):
        key = feature["properties"]["map_id"]
        return {
            "fillColor": percentage_shade(
                selected_number, highlight.get(key, 0.0)
            ) if mode == "Votação de candidato"
                         else color_by_key.get(key, "#44475a"),
            # Cor cheia e borda escura fina, como no mapa de apuracao do g1.
            "fillOpacity": 1.0,
            "color": "#161717", "weight": 0.45,
        }

    fields = ["nome_tooltip"]
    aliases = ["Município" if level == "Município" else "Zona eleitoral"]
    if level == "Município":
        fields.append("codigo_tooltip")
        aliases.append("Código IBGE")
    fields.extend(["primeiro", "segundo", "margem"])
    aliases.extend(["Mais votado", "2º colocado", "Diferença"])
    if "destaque" in attributes:
        fields.append("destaque")
        aliases.append(f"{escape(str(selected))} (% válidos)")
    if level == "Município" and uf != "Todas":
        # Recorte menor que a UF (municipio ou zona escolhidos): o resto da
        # UF aparece apagado, como no g1, em vez de sumir do mapa.
        prefix = UF_PREFIX.get(uf, "")
        rest = all_geometry.loc[
            [str(code).startswith(prefix) and code not in keys
             for code in all_geometry["map_id"]]
        ]
        if prefix and not rest.empty:
            context_layer(json.loads(rest[["map_id", "geometry"]].to_json(drop_id=True))).add_to(map_view)
    results_layer = folium.GeoJson(
        geojson, name="Resultados", style_function=style,
        highlight_function=lambda _: {"weight": 1.5, "color": "#f8f8f2"},
        tooltip=folium.GeoJsonTooltip(fields=fields, aliases=aliases, sticky=False),
    ).add_to(map_view)
    if level == "Município" and detail != ZONE_DETAIL and len(geometry) > 1:
        # Clique/zoom acendem a cidade e apagam as demais (no navegador).
        map_view.add_child(CityFocus(results_layer))
    map_view.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])
    map_view.get_root().html.add_child(folium.Element(legend_html(
        "percentual" if mode == "Votação de candidato" else "margem"
    )))
    render_explorer(
        map_view, geometry, crosswalk() if level == "Município" else None,
        root=DATA, year=year, uf=uf, cargo=cargo, turno=turno,
        municipio=municipality, zona=zone, mode=mode,
        candidate_number=selected_number, detail=detail,
        section_ready=section_ready and level == "Município",
        zone_votes=zone_votes if level == "Município" else None,
        district_votes=district_votes if level == "Município" else None,
    )



st.title("🗳️ Atlas Eleitoral")
st.caption("Dados públicos do Tribunal Superior Eleitoral · Estudo independente · Sem vínculo com TSE ou G1")
years = sorted((int(path.name) for path in (DATA / "serving").glob("20[0-9][0-9]")
                if path.is_dir() and (path / "catalog.json").exists()), reverse=True)
if not years:
    st.error("Os resultados eleitorais ainda nao estao disponiveis neste Atlas.")
    st.stop()

with st.sidebar:
    year = st.selectbox("Eleição", years)
    votes, overlapping_rows = load_votes(year)
    catalog = load_catalog(year)
    if votes.is_empty():
        st.info("Ainda nao ha resultados eleitorais carregados para este ano.")
        st.stop()
    uf_opts = sorted(votes.get_column("uf").drop_nulls().unique().to_list())
    uf = st.selectbox("UF", ["Todas"] + uf_opts)
    if uf != "Todas":
        votes = votes.filter(pl.col("uf") == uf)
    # O cargo deve vir ANTES do turno: deputados e senadores nao sao
    # candidatos do segundo turno e nao podem desaparecer do seletor.
    cargos = available_offices(votes)
    if not cargos:
        st.info("Nao ha resultados para esta unidade federativa no conjunto carregado.")
        st.stop()
    cargo = st.selectbox("Cargo", cargos, index=preferred_office(cargos))
    votes = votes.filter(pl.col("cargo") == cargo)
    turnos = available_turns(votes, cargo)
    if not turnos:
        st.info("Nao ha turnos disponiveis para o cargo selecionado.")
        st.stop()
    # Os dois turnos ficam visiveis sempre. Um turno sem registros e
    # identificado explicitamente como ausente, nunca preenchido artificialmente.
    turno = st.selectbox(
        "Turno", [1, 2],
        index=0,
        format_func=lambda value: round_label(value, turnos),
        key=f"turno_{year}_{uf}_{cargo}",
    )
    if turno not in turnos:
        st.info(
            f"Os resultados do {turno}º turno para {cargo} ainda "
            "nao estao presentes nos dados eleitorais carregados."
        )
        st.stop()
    votes = votes.filter(pl.col("turno") == turno)
    # UF inteira, antes de municipio/zona: a zona aproximada completa soma
    # todos os municipios que ela abrange.
    votes_uf = votes
    if len(cargos) == 1:
        st.caption(
            f"Para a UF selecionada, apenas {cargos[0]} esta disponivel "
            "no conjunto carregado."
        )
    # Selecao por codigo TSE + UF: nomes se repetem entre estados
    # (ex.: "Bom Jesus"), entao o nome e apenas rotulo.
    municipalities = (
        votes.select(["uf", "cd_municipio_tse", "municipio"])
        .unique(subset=["uf", "cd_municipio_tse"], keep="first")
        .sort(["municipio", "uf"])
    )
    municipality_labels = {
        (row["uf"], row["cd_municipio_tse"]): f'{row["municipio"]} ({row["uf"]})'
        for row in municipalities.iter_rows(named=True)
    }
    municipality_key = st.selectbox(
        "Município", [None] + list(municipality_labels),
        format_func=lambda key: "Todos" if key is None else municipality_labels[key],
    )
    municipality = (
        "Todos" if municipality_key is None
        else municipality_labels[municipality_key]
    )
    if municipality_key is not None:
        votes = votes.filter(
            (pl.col("uf") == municipality_key[0])
            & (pl.col("cd_municipio_tse") == municipality_key[1])
        )
    # Votos antes do filtro de zona: as camadas de zona mostram todas as
    # zonas e destacam a escolhida (como no mapa de apuracao).
    votes_all_zones = votes
    zones = sorted(votes.get_column("zona").unique().to_list())
    pending_zone = st.session_state.pop(PENDING_ZONE, None)
    if pending_zone is not None and pending_zone in zones:
        # Zona clicada no mapa por zona preenche o seletor.
        st.session_state["atlas_zone_select"] = pending_zone
    if st.session_state.get("atlas_zone_select", "Todas") not in ["Todas"] + zones:
        st.session_state["atlas_zone_select"] = "Todas"
    zone = st.selectbox("Zona", ["Todas"] + zones, key="atlas_zone_select")
    if zone != "Todas":
        votes = votes.filter(pl.col("zona") == zone)
    # Sem poligonos cartograficos reais de zonas, a interface sempre
    # usa municipios. A selecao de zona continua filtrando votos, mas
    # nunca apresenta um municipio como poligono eleitoral de zona.
    zone_shape_available = (DATA / "geo" / "zonas.geojson").is_file()
    section_ready = (
        (DATA / "serving" / str(year) / "secoes" / "catalog.json").exists()
        and (DATA / "serving" / str(year) / "locais.parquet").exists()
    )
    # O modo automático sempre começa no mapa nacional/estadual; os
    # pontos das seções aparecem conforme a aproximação pelo mouse.
    levels = ["Automático"] + geometry_options(zone_shape_available)
    if not zone_shape_available and districts_available(DATA):
        # Sem malha oficial: zona inteira aproximada (setores IBGE 2022).
        levels.append(ZONE_DETAIL)
    if section_ready:
        levels.append("Seção eleitoral (locais)")
    level = st.radio("Detalhamento geográfico", levels, index=0)
    if level in ("Automático", "Seção eleitoral (locais)"):
        st.caption(
            "Navegação no próprio mapa: hover mostra resultados; "
            "o zoom revela as zonas e o clique carrega os locais de votação."
        )
    elif level == ZONE_DETAIL:
        st.caption(
            "Zonas com contorno aproximado (setores IBGE 2022 + locais TSE), "
            "não oficial. Clique numa zona para selecioná-la."
        )
    if zone != "Todas":
        st.caption(
            "O filtro corresponde aos votos da zona, não ao perímetro "
            "territorial de uma seção."
        )
    mode = st.radio("Visualização", ["Vencedor por região", "Votação de candidato"])
    st.caption(
        "Legenda: 🔴 PT (13) · 🔵 PL (22) "
        "· demais legendas com cores distintas. "
        "No mapa de vencedor, a cor é do líder e a intensidade é a "
        "diferença em pontos percentuais para o 2º colocado."
    )
    total_per_candidate = (
        votes.filter(pl.col("tipo_voto") == "nominal")
        .group_by("candidato").agg(pl.col("votos").sum())
        .sort("votos", descending=True)
    )
    candidate = (
        st.selectbox("Candidato", total_per_candidate.get_column("candidato").to_list())
        if mode == "Votação de candidato" and not total_per_candidate.is_empty()
        else None
    )


# Transparencia de cobertura calculada durante a preparacao do dataset.
# Sao informacoes ao leitor do mapa, nunca instrucoes de terminal.
if overlapping_rows:
    st.caption(
        f"{overlapping_rows:,} registros estaduais repetidos do arquivo "
        "nacional foram desconsiderados para não contar votos em dobro."
        .replace(",", ".")
    )
coverage = catalog.get("cobertura", {})
if coverage:
    state_count = coverage.get("ufs_importadas", 0)
    expected = coverage.get("ufs_esperadas", 27)
    missing = coverage.get("ufs_ausentes", [])
    if missing:
        st.caption(
            f"Cobertura territorial carregada: {state_count}/{expected} UFs. "
            f"Arquivos estaduais ausentes: {', '.join(missing)}."
        )
    else:
        st.caption(
            f"Arquivos estaduais disponíveis: {state_count}/{expected} UFs. "
            "A conferência dos arquivos não substitui a totalização oficial."
        )


def total_votos(tipo: str) -> int:
    return int(votes.filter(pl.col("tipo_voto") == tipo).get_column("votos").sum() or 0)


nominais = total_votos("nominal")
validos = nominais + total_votos("legenda")
brancos = total_votos("branco")
nulos = total_votos("nulo")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Votos válidos", f"{validos:,}".replace(",", "."))
m2.metric("Brancos", f"{brancos:,}".replace(",", "."))
m3.metric("Nulos", f"{nulos:,}".replace(",", "."))
m4.metric("Zonas representadas", votes.select(["uf", "zona"]).unique().height)

left, right = st.columns([3, 1], gap="large")
with left:
    # Auto e seções preservam a malha municipal como base permanente.
    # Somente o modo de zona explicito usa uma geometria real de zonas.
    effective_level = (
        "Município" if level in ("Automático", "Seção eleitoral (locais)", ZONE_DETAIL)
        else level
    )
    polygons = load_shape(effective_level)
    if polygons is None:
        st.info("A camada territorial deste recorte não está disponível.")
    else:
        try:
            boundaries, scoped = shape_for_votes(
                polygons, votes, effective_level
            )
            matched = scoped.filter(
                pl.col("map_id").is_not_null()
                & (pl.col("map_id") != "")
            )
            if matched.height < scoped.height:
                st.caption(
                    f"{scoped.height - matched.height:,} registros sem "
                    "correspondência cartográfica neste recorte."
                )
            draw_map(
                boundaries, matched, mode, candidate, effective_level,
                year=year, uf=uf, cargo=cargo, turno=turno,
                municipality=municipality, zone=zone, detail=level,
                section_ready=section_ready,
                zone_votes=attach_ibge(votes_all_zones)
                if effective_level == "Município" else None,
                district_votes=votes_uf if level == ZONE_DETAIL else None,
            )
        except (ValueError, KeyError, pl.exceptions.PolarsError) as exc:
            st.error(f"Mapa não disponível: {exc}")

with right:
    st.subheader(f"{cargo} · {turno}º turno")
    for record in total_per_candidate.head(12).iter_rows(named=True):
        pct = 100 * record["votos"] / validos if validos else 0
        st.markdown(
            f'**{record["candidato"]}** — {br_number(record["votos"], 0)} votos'
            f' · {br_number(pct)}% dos válidos'
        )
        st.progress(min(1.0, pct / 100))
    st.caption(
        f"{len(uf_opts)} UFs no conjunto consultado. "
        "A disponibilidade depende dos arquivos oficiais incorporados."
    )

st.subheader("Detalhamento por zona eleitoral")
zone_keys = ["uf", "cd_municipio_tse", "municipio", "zona"]
zone_results = region_results(votes, zone_keys)
if zone_results.is_empty():
    st.info("Sem votos nominais por zona neste recorte.")
else:
    blank_null = (
        votes.filter(pl.col("tipo_voto").is_in(["branco", "nulo"]))
        .group_by(zone_keys + ["tipo_voto"]).agg(pl.col("votos").sum())
        .pivot(on="tipo_voto", index=zone_keys, values="votos")
    )
    for column in ("branco", "nulo"):
        if column not in blank_null.columns:
            blank_null = blank_null.with_columns(pl.lit(0, pl.Int64).alias(column))
    zone_view = (
        zone_results.join(blank_null, on=zone_keys, how="left")
        .with_columns(pl.col("branco", "nulo").fill_null(0))
        .sort(["uf", "municipio", "zona"])
        .select(
            pl.col("uf").alias("UF"),
            pl.col("municipio").alias("Município"),
            pl.col("zona").alias("Zona"),
            pl.col("candidato_1").alias("1º colocado"),
            pl.col("pct_1").round(2).alias("% 1º"),
            pl.col("candidato_2").alias("2º colocado"),
            pl.col("pct_2").round(2).alias("% 2º"),
            pl.when(pl.col("empate")).then(None)
            .otherwise(pl.col("margem_pp").round(2)).alias("Diferença (p.p.)"),
            pl.col("empate").alias("Empate"),
            pl.col("total_validos").alias("Válidos"),
            pl.col("branco").alias("Brancos"),
            pl.col("nulo").alias("Nulos"),
        )
    )
    st.dataframe(zone_view, width="stretch", hide_index=True)
table = (
    votes.group_by(["uf", "municipio", "zona", "cargo", "numero", "candidato", "tipo_voto"])
    .agg(pl.col("votos").sum())
    .sort("votos", descending=True)
)
with st.expander("Votos por candidato e zona (dados completos)"):
    st.dataframe(table, width="stretch", hide_index=True)
st.download_button("Exportar seleção CSV", table.write_csv().encode("utf-8-sig"),
                   file_name=f"atlas_{year}_turno{turno}.csv", mime="text/csv")