"""Pagina 3D experimental, independente do Atlas Folium."""
from __future__ import annotations

from pathlib import Path

import polars as pl
import pydeck as pdk
import streamlit as st

from mapa_eleicoes.dashboard_options import round_label
from mapa_eleicoes.electoral_3d import (
    MODES, columns_for_map, load_geometry, load_reference, load_votes, municipal_totals,
)
from mapa_eleicoes.office_catalog import available_offices, available_turns, preferred_office
from mapa_eleicoes.results import br_number

DATA = Path(__file__).resolve().parents[1] / "data"

st.set_page_config(page_title="Mapa eleitoral 3D", page_icon="📊", layout="wide")
st.markdown("""<style>
[data-testid="stAppViewContainer"] {background:#191923;color:#f8f8f2}
[data-testid="stSidebar"] {background:#252536}
.block-container {max-width:1750px;padding-top:1.2rem}
</style>""", unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def cached_votes(year: int, stamp: tuple) -> tuple[pl.DataFrame, int]:
    return load_votes(DATA, year)


@st.cache_data(show_spinner=False)
def cached_geography(stamp: int) -> tuple[pl.DataFrame, dict]:
    return load_geometry(DATA)


@st.cache_data(show_spinner=False)
def cached_reference(stamp: int) -> pl.DataFrame:
    return load_reference(DATA)


st.title("📊 Mapa eleitoral 3D · laboratório")
st.caption("Dados oficiais TSE disponíveis localmente · Geografia oficial IBGE · Experimento independente")
years = sorted([
    int(p.name) for p in (DATA / "serving").glob("20[0-9][0-9]")
    if p.is_dir() and any(p.glob("votos_*.parquet"))
], reverse=True)
if not years:
    st.info("Ainda não há resultados eleitorais preparados para este ano.")
    st.stop()

with st.sidebar:
    st.subheader("Colunas 3D")
    year = st.selectbox("Eleição", years)
    folder = DATA / "serving" / str(year)
    stamp = tuple((p.name, p.stat().st_mtime_ns) for p in sorted(folder.glob("votos_*.parquet")))
    votes, discarded = cached_votes(year, stamp)
    if votes.is_empty():
        st.warning("Sem votos neste conjunto.")
        st.stop()
    states = sorted(votes["uf"].drop_nulls().unique().to_list())
    uf = st.selectbox("UF", ["Todas", *states])
    if uf != "Todas":
        votes = votes.filter(pl.col("uf") == uf)
    cargos = available_offices(votes)
    if not cargos:
        st.warning("Nenhum cargo disponível.")
        st.stop()
    cargo = st.selectbox("Cargo", cargos, index=preferred_office(cargos))
    votes = votes.filter(pl.col("cargo") == cargo)
    turns = available_turns(votes, cargo)
    turno = st.selectbox(
        "Turno", [1, 2], format_func=lambda value: round_label(value, turns),
        key=f"turno_3d_{year}_{uf}_{cargo}",
    )
    if turno not in turns:
        st.info("Este turno não está disponível no conjunto oficial carregado.")
        st.stop()
    votes = votes.filter(pl.col("turno") == turno)
    mode = st.radio("Altura das barras", MODES)
    candidate = None
    if mode == "Votos do candidato":
        ranking = (
            votes.filter(pl.col("tipo_voto") == "nominal")
            .group_by(["numero", "candidato"])
            .agg(pl.col("votos").sum().alias("total"))
            .sort(["total", "numero"], descending=[True, False])
            .to_dicts()
        )
        if not ranking:
            st.warning("Não há candidatos nominais disponíveis.")
            st.stop()
        candidates = {row["numero"]: row["candidato"] for row in ranking}
        candidate = st.selectbox(
            "Candidato", list(candidates),
            format_func=lambda num: f"{candidates[num]} ({num})",
        )
    municipalities = (
        votes.select(["uf", "cd_municipio_tse", "municipio"])
        .unique(subset=["uf", "cd_municipio_tse"])
        .sort(["municipio", "uf"]).to_dicts()
    )
    labels = {
        (record["uf"], record["cd_municipio_tse"]):
        f'{record["municipio"]} ({record["uf"]})' for record in municipalities
    }
    city = st.selectbox(
        "Município", [None, *labels],
        format_func=lambda key: "Todos" if key is None else labels[key],
        key=f"city_3d_{year}_{uf}_{cargo}_{turno}",
    )
    if city is not None:
        votes = votes.filter(
            (pl.col("uf") == city[0]) & (pl.col("cd_municipio_tse") == city[1])
        )
    max_height = st.slider("Altura visual máxima (m)", 40000, 300000, 160000, 20000)
    radius = st.slider("Raio das colunas (m)", 200, 3000, 750, 50)

geo = DATA / "geo" / "municipios.geojson"
reference = DATA / "reference" / "tse_ibge.csv"
if not geo.is_file() or not reference.is_file():
    st.warning("Esta camada requer a malha municipal IBGE e o de/para TSE/IBGE locais.")
    st.stop()
try:
    refs = cached_reference(reference.stat().st_mtime_ns)
    points, boundaries = cached_geography(geo.stat().st_mtime_ns)
    result = municipal_totals(votes, refs, candidate=candidate)
    columns, diag = columns_for_map(
        result, points, mode, candidate=candidate, max_height=max_height,
    )
except (ValueError, FileNotFoundError) as error:
    st.error(f"Não foi possível construir a camada: {error}")
    st.stop()
if not columns:
    st.warning("Não há municípios com votos nominais e geografia associada para esse filtro.")
    st.stop()

m1, m2, m3 = st.columns(3)
m1.metric("Municípios representados", br_number(len(columns), 0))
m2.metric("Sem de/para", diag["sem_de_para"])
m3.metric("Sem malha IBGE", diag["sem_geometria"])

lat = [record["latitude"] for record in columns]
lon = [record["longitude"] for record in columns]
center_lat, center_lon = (min(lat) + max(lat)) / 2, (min(lon) + max(lon)) / 2
zoom = 9.0 if city is not None else 5.0 if uf != "Todas" else 3.3

layers = [
    pdk.Layer(
        "GeoJsonLayer", data=boundaries, id="limites-estaduais",
        filled=True, stroked=True, pickable=False,
        get_fill_color=[36, 38, 52, 255],
        get_line_color=[185, 190, 211, 240],
        get_line_width=500, line_width_min_pixels=1,
    ),
    pdk.Layer(
        "ColumnLayer", data=columns, id="colunas-municipais",
        get_position="[longitude, latitude]",
        get_elevation="elevation", get_fill_color="color",
        radius=radius, disk_resolution=4, extruded=True,
        pickable=True, auto_highlight=True,
    ),
]
tooltip = {
    "html": (
        "<b>{municipio} ({uf})</b><br/>"
        "1º: {primeiro} · {votos_primeiro} votos<br/>"
        "2º: {segundo} · {votos_segundo} votos<br/>"
        "Diferença: {margem_votos} votos ({margem_pp} p.p.)<br/>"
        "Métrica: <b>{metrica}</b>"
    ),
    "style": {"backgroundColor": "#282a36", "color": "#f8f8f2", "fontSize": "12px"},
}
# Sem retorno de zoom/pan ao Streamlit: movimentos nao provocam rerun.
st.pydeck_chart(
    pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(
            latitude=center_lat, longitude=center_lon, zoom=zoom, pitch=52, bearing=0,
        ),
        map_style=None,  # nenhuma chave Mapbox/CARTO
        tooltip=tooltip,
    ),
    width="stretch", height=720,
)
st.caption(
    "Cada barra representa um município e está em um ponto representativo dentro "
    "do polígono IBGE — não é um local de votação nem uma zona eleitoral. "
    "Vermelho: número 13; azul: número 22; demais números: cores próprias. "
    "No modo candidato, a cor identifica o candidato escolhido; empate em cinza nos demais modos."
)
st.caption(
    "Escala de altura **não linear**: raiz quadrada do valor, limitada ao percentil 99 "
    f"do recorte ({br_number(diag['p99'], 2)}). "
    "Altura visual não é altitude geográfica; valores exatos aparecem no hover. "
    "Cobertura limitada aos dados oficiais presentes nos Parquets locais."
)
if discarded:
    st.caption(
        f"Integridade: {br_number(discarded, 0)} linhas estaduais duplicadas em BR "
        "foram excluídas antes de calcular os municípios."
    )
