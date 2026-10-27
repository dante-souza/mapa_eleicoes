"""Atlas Eleitoral. O unico ponto de entrada operacional e make run.

Polars: dados/votos/joins/agrupamentos. GeoPandas: exclusivamente geometria.
Nao converter Arrow/Polars para pandas nem fazer GeoDataFrame.merge com Polars.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import folium
import geopandas as gpd
import polars as pl
import streamlit as st
from streamlit_folium import st_folium

from mapa_eleicoes.geo_bridge import add_properties, ibge_code, zone_code

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
COLORS = ["#ff5555", "#6272a4", "#bd93f9", "#50fa7b",
          "#ffb86c", "#8be9fd", "#f1fa8c", "#ff79c6"]
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
    files = sorted((DATA / "processed" / str(year)).glob("votos_*.csv.gz"))
    if not files:
        return pl.DataFrame()
    parts = []
    for path in files:
        # CSV derivado: tipos fixos. Identificadores nunca inferidos como inteiros.
        with gzip.open(path, "rb") as stream:
            frame = pl.read_csv(stream, infer_schema=False)
        frame = frame.with_columns(
            pl.col("ano").cast(pl.Int32, strict=True),
            pl.col("turno").cast(pl.Int16, strict=True),
            pl.col("zona").cast(pl.Int32, strict=True),
            pl.col("votos").cast(pl.Int64, strict=True),
            *[pl.col(name).fill_null("").cast(pl.String) for name in TEXT_COLUMNS],
        )
        parts.append(frame)
    return pl.concat(parts, how="vertical")


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
            raise ValueError("Falta data/reference/tse_ibge.csv (make crosswalk).")
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
    totals = (
        data.filter(pl.col("tipo_voto") == "nominal")
        .group_by("candidato").agg(pl.col("votos").sum())
        .sort("votos", descending=True)
    )
    colors = {candidate: COLORS[i % len(COLORS)]
              for i, candidate in enumerate(totals.get_column("candidato").to_list())}
    if mode == "Votação de candidato" and selected:
        candidate_votes = (
            data.filter((pl.col("tipo_voto") == "nominal") & (pl.col("candidato") == selected))
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
    display["nome_tooltip"] = [str(value) for value in joined["map_id"]]
    display["vencedor"] = [str(value or "Sem dados") for value in joined["candidato"]]
    display["votos_vencedor"] = [int(value or 0) for value in joined["votos"]]
    display["percentual_vencedor"] = [round(float(value or 0), 2) for value in joined["pct"]]
    if "destaque" in attributes:
        display["destaque"] = [round(float(value or 0), 2) for value in joined["destaque"]]
    geojson = json.loads(display.to_json(drop_id=True))
    color_by_key = dict(zip(joined["map_id"], [
        colors.get(name, "#44475a") for name in joined["candidato"]
    ]))
    highlight = dict(zip(joined["map_id"], [
        float(value or 0) for value in joined.get("destaque", [0] * len(joined))
    ]))
    centroid = geometry.geometry.union_all().representative_point()
    bounds = geometry.total_bounds
    map_view = folium.Map(location=[float(centroid.y), float(centroid.x)],
                          zoom_start=5, tiles="CartoDB dark_matter",
                          control_scale=True, prefer_canvas=True)

    def style(feature):
        key = feature["properties"]["map_id"]
        intensity = min(1.0, max(0.05, highlight.get(key, 0) / 100.0))
        return {
            "fillColor": colors.get(selected, "#ff5555") if mode == "Votação de candidato"
                         else color_by_key.get(key, "#44475a"),
            "fillOpacity": 0.15 + 0.8 * intensity if mode == "Votação de candidato" else 0.78,
            "color": "#11111b", "weight": 0.45,
        }

    fields = ["nome_tooltip", "vencedor", "votos_vencedor", "percentual_vencedor"]
    aliases = ["Código geográfico", "Mais votado", "Votos do líder", "% dos válidos"]
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
years = sorted((int(path.name) for path in (DATA / "processed").glob("20[0-9][0-9]")
                if path.is_dir()), reverse=True)
if not years:
    st.warning("Sem dados processados. Use make import e make ingest.")
    st.stop()

with st.sidebar:
    year = st.selectbox("Eleição", years)
    votes = load_votes(year)
    if votes.is_empty():
        st.warning("Ano sem arquivos CSV agregados.")
        st.stop()
    uf_opts = sorted(votes.get_column("uf").drop_nulls().unique().to_list())
    uf = st.selectbox("UF", ["Todas"] + uf_opts)
    if uf != "Todas":
        votes = votes.filter(pl.col("uf") == uf)
    turnos = sorted(votes.get_column("turno").unique().to_list())
    turno = st.selectbox("Turno", turnos)
    votes = votes.filter(pl.col("turno") == turno)
    cargo = st.selectbox("Cargo", sorted(votes.get_column("cargo").unique().to_list()))
    votes = votes.filter(pl.col("cargo") == cargo)
    municipality = st.selectbox("Município",
                                ["Todos"] + sorted(votes.get_column("municipio").unique().to_list()))
    if municipality != "Todos":
        votes = votes.filter(pl.col("municipio") == municipality)
    zones = sorted(votes.get_column("zona").unique().to_list())
    zone = st.selectbox("Zona", ["Todas"] + zones)
    if zone != "Todas":
        votes = votes.filter(pl.col("zona") == zone)
    level = st.radio("Geometria", ["Município", "Zona eleitoral"],
                     help="Zona exige polígonos reais.")
    if level == "Município" and zone != "Todas":
        st.warning("O limite exibido e municipal, nao da zona selecionada.")
    mode = st.radio("Visualização", ["Vencedor por região", "Votação de candidato"])
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
        st.warning(f"Sem malha geográfica de {level.lower()}. Importe usando make geo-import.")
    else:
        try:
            boundaries, scoped = shape_for_votes(polygons, votes, level)
            matched = scoped.filter(pl.col("map_id").is_not_null() & (pl.col("map_id") != ""))
            if matched.height < scoped.height:
                st.info(f"{scoped.height - matched.height} linhas sem correspondência geográfica.")
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
    st.caption(f"{len(uf_opts)} UFs no conjunto processado; cobertura pode ser parcial.")

st.subheader("Detalhamento por zona eleitoral")
table = (
    votes.group_by(["uf", "municipio", "zona", "cargo", "numero", "candidato", "tipo_voto"])
    .agg(pl.col("votos").sum())
    .sort("votos", descending=True)
)
st.dataframe(table, use_container_width=True, hide_index=True)
st.download_button("Exportar seleção CSV", table.write_csv().encode("utf-8-sig"),
                   file_name=f"atlas_{year}_turno{turno}.csv", mime="text/csv")