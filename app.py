"""Atlas Eleitoral. O unico ponto de entrada operacional e make run.

Polars: dados/votos/joins/agrupamentos. GeoPandas: exclusivamente geometria.
Nao converter Arrow/Polars para pandas nem fazer GeoDataFrame.merge com Polars.
"""
from __future__ import annotations

import json
from pathlib import Path

import folium
import geopandas as gpd
import polars as pl
import streamlit as st
from streamlit_folium import st_folium

from mapa_eleicoes.geo_bridge import add_properties, ibge_code, zone_code
from mapa_eleicoes.map_tiles import atlas_map
from mapa_eleicoes.party_colors import color_for_number
from mapa_eleicoes.office_catalog import available_offices, available_turns, preferred_office
from mapa_eleicoes.dashboard_options import round_label, geometry_options

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
def load_votes(year: int) -> pl.DataFrame:
    """Consome exclusivamente dados finais Parquet gerados antes da interface."""
    folder = DATA / "serving" / str(year)
    files = sorted(folder.glob("votos_*.parquet"))
    if not files:
        return pl.DataFrame()
    return pl.concat([pl.read_parquet(path) for path in files], how="vertical")


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
        votes = votes.join(unique, on=["uf", "cd_municipio_tse"], how="left",
                           validate="m:1").with_columns(
                               pl.col("codigo_ibge").fill_null("").alias("map_id"))
        code_col = field(geometry, ["CD_MUN", "CD_GEOCMU", "codarea",
                                    "codigo_ibge", "code_muni", "id", "CD_MUN_IBGE"])
        if not code_col:
            raise ValueError("Malha municipal sem codigo IBGE de 7 digitos.")
        geometry["map_id"] = [ibge_code(value) for value in geometry[code_col]]
    return geometry, votes


def winner_table(frame: pl.DataFrame) -> pl.DataFrame:
    nominal = frame.filter(pl.col("tipo_voto") == "nominal")
    if nominal.is_empty():
        return pl.DataFrame()
    grouped = nominal.group_by(["map_id", "numero", "candidato"]).agg(pl.col("votos").sum())
    totals = grouped.group_by("map_id").agg(pl.col("votos").sum().alias("total_validos"))
    return (
        grouped.join(totals, on="map_id", how="left")
        .with_columns((100.0 * pl.col("votos") / pl.col("total_validos")).alias("pct"))
        .sort(["map_id", "votos", "numero"], descending=[False, True, False])
        .unique(subset=["map_id"], keep="first", maintain_order=True)
    )


def draw_map(geometry: gpd.GeoDataFrame, data: pl.DataFrame, mode: str,
             selected: str | None, level: str):
    winners = winner_table(data)
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
            (100.0 * pl.col("votos_candidato") / pl.col("total_validos"))
            .alias("destaque")
        )

    keys = set(data.get_column("map_id").drop_nulls().to_list())
    geometry = geometry.loc[geometry["map_id"].isin(keys) & geometry.geometry.notna()].copy()
    if geometry.empty:
        st.warning("Nao foi possivel associar os votos a malha. Revise as chaves.")
        return
    # Fronteira estavel: conversao Polars -> registros Python tipados (nao DataFrame pandas).
    attributes = {
        "candidato": "Sem dados",
        "numero": "",
        "votos": 0,
        "pct": 0.0,
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
    display["vencedor"] = [str(value or "Sem dados") for value in joined["candidato"]]
    display["votos_vencedor"] = [int(value or 0) for value in joined["votos"]]
    display["percentual_vencedor"] = [round(float(value or 0), 2) for value in joined["pct"]]
    if "destaque" in attributes:
        display["destaque"] = [round(float(value or 0), 2) for value in joined["destaque"]]
    geojson = json.loads(display.to_json(drop_id=True))
    color_by_key = dict(zip(joined["map_id"], [
        color_for_number(number) for number in joined["numero"]
    ]))
    highlight = dict(zip(joined["map_id"], [
        float(value or 0) for value in joined.get("destaque", [0] * len(joined))
    ]))
    centroid = geometry.geometry.union_all().representative_point()
    bounds = geometry.total_bounds
    map_view = atlas_map([float(centroid.y), float(centroid.x)])

    def style(feature):
        key = feature["properties"]["map_id"]
        intensity = min(1.0, max(0.05, highlight.get(key, 0) / 100.0))
        return {
            "fillColor": color_for_number(selected_number) if mode == "Votação de candidato"
                         else color_by_key.get(key, "#44475a"),
            "fillOpacity": 0.15 + 0.8 * intensity if mode == "Votação de candidato" else 0.78,
            "color": "#11111b", "weight": 0.45,
        }

    fields = ["nome_tooltip"]
    aliases = ["Município" if level == "Município" else "Zona eleitoral"]
    if level == "Município":
        fields.append("codigo_tooltip")
        aliases.append("Código IBGE")
    fields.extend(["vencedor", "votos_vencedor", "percentual_vencedor"])
    aliases.extend(["Mais votado", "Votos do líder", "% dos válidos"])
    if "destaque" in attributes:
        fields.append("destaque")
        aliases.append("% do candidato")
    folium.GeoJson(
        geojson, name="Resultados", style_function=style,
        highlight_function=lambda _: {"weight": 1.5, "color": "#f8f8f2"},
        tooltip=folium.GeoJsonTooltip(fields=fields, aliases=aliases, sticky=False),
    ).add_to(map_view)
    map_view.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])
    st_folium(map_view, height=700, returned_objects=[], use_container_width=True)
    st.caption(f"{len(display)} polígonos exibidos · Geometria: {level} · Sem inferir zonas")



st.title("🗳️ Atlas Eleitoral")
st.caption("Dados públicos do Tribunal Superior Eleitoral · Estudo independente · Sem vínculo com TSE ou G1")
years = sorted((int(path.name) for path in (DATA / "serving").glob("20[0-9][0-9]")
                if path.is_dir() and (path / "catalog.json").exists()), reverse=True)
if not years:
    st.error("Os resultados eleitorais ainda nao estao disponiveis neste Atlas.")
    st.stop()

with st.sidebar:
    year = st.selectbox("Eleição", years)
    votes = load_votes(year)
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
    if len(cargos) == 1:
        st.caption(
            f"Para a UF selecionada, apenas {cargos[0]} esta disponivel "
            "no conjunto carregado."
        )
    municipality = st.selectbox("Município",
                                ["Todos"] + sorted(votes.get_column("municipio").unique().to_list()))
    if municipality != "Todos":
        votes = votes.filter(pl.col("municipio") == municipality)
    zones = sorted(votes.get_column("zona").unique().to_list())
    zone = st.selectbox("Zona", ["Todas"] + zones)
    if zone != "Todas":
        votes = votes.filter(pl.col("zona") == zone)
    # Sem poligonos cartograficos reais de zonas, a interface sempre
    # usa municipios. A selecao de zona continua filtrando votos, mas
    # nunca apresenta um municipio como poligono eleitoral de zona.
    zone_shape_available = (DATA / "geo" / "zonas.geojson").is_file()
    levels = geometry_options(zone_shape_available)
    if len(levels) > 1:
        level = st.radio("Geometria", levels)
    else:
        level = levels[0]
        st.caption("Mapa municipal. A votacao por zona aparece nos filtros e na tabela.")
    if level == "Município" and zone != "Todas":
        st.caption("Os votos refletem a zona escolhida; o contorno e do municipio.")
    mode = st.radio("Visualização", ["Vencedor por região", "Votação de candidato"])
    st.caption(
        f"Legenda: 🔴 PT (13) · 🔵 PL (22) "
        "· demais legendas com cores distintas. "
        "A cor corresponde ao número eleitoral."
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


validos = total_votos("nominal")
brancos = total_votos("branco")
nulos = total_votos("nulo")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Votos nominais", f"{validos:,}".replace(",", "."))
m2.metric("Brancos", f"{brancos:,}".replace(",", "."))
m3.metric("Nulos", f"{nulos:,}".replace(",", "."))
m4.metric("Zonas representadas", votes.select(["uf", "zona"]).unique().height)

left, right = st.columns([3, 1], gap="large")
with left:
    polygons = load_shape(level)
    if polygons is None:
        st.info("A camada territorial desta visualizacao nao esta disponivel no conjunto de dados.")
    else:
        try:
            boundaries, scoped = shape_for_votes(polygons, votes, level)
            matched = scoped.filter(pl.col("map_id").is_not_null() & (pl.col("map_id") != ""))
            if matched.height < scoped.height:
                st.caption(
                    f"{scoped.height - matched.height:,} registros nao puderam "
                    "ser associados ao mapa territorial."
                )
            draw_map(boundaries, matched, mode, candidate, level)
        except (ValueError, KeyError, pl.exceptions.PolarsError) as exc:
            st.error(f"Mapa indisponível: {exc}")

with right:
    st.subheader(f"{cargo} · {turno}º turno")
    total = int(total_per_candidate.get_column("votos").sum() or 0)
    for record in total_per_candidate.head(12).iter_rows(named=True):
        pct = 100 * record["votos"] / total if total else 0
        st.markdown(f'**{record["candidato"]}** — {record["votos"]:,} votos · {pct:.2f}%')
        st.progress(min(1.0, pct / 100))
    st.caption(
        f"{len(uf_opts)} UFs no conjunto consultado. "
        "A disponibilidade depende dos arquivos oficiais incorporados."
    )

st.subheader("Detalhamento por zona eleitoral")
table = (
    votes.group_by(["uf", "municipio", "zona", "cargo", "numero", "candidato", "tipo_voto"])
    .agg(pl.col("votos").sum())
    .sort("votos", descending=True)
)
st.dataframe(table, width="stretch", hide_index=True)
st.download_button("Exportar seleção CSV", table.write_csv().encode("utf-8-sig"),
                   file_name=f"atlas_{year}_turno{turno}.csv", mime="text/csv")