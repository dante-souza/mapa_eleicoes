"""Página de deltas e viradas independente da apuração existente."""
from pathlib import Path
import geopandas as gpd
import polars as pl
import streamlit as st
from streamlit_folium import st_folium
from mapa_eleicoes.swing import swing_results, state_swing_results
from mapa_eleicoes.vote_sources import combine_sources
from mapa_eleicoes.zone_geometry import zone_file, UF_PREFIX
from mapa_eleicoes.swing_layers import delta_map

DATA = Path(__file__).resolve().parents[1] / "data"
st.set_page_config(page_title="Deltas e viradas", layout="wide", page_icon="↗")
st.markdown('<style>[data-testid="stAppViewContainer"]{background:#191923;color:#f8f8f2}[data-testid="stSidebar"]{background:#252536}.block-container{max-width:1750px}</style>', unsafe_allow_html=True)

@st.cache_data(show_spinner=False)
def read_votes(year, stamps):
    paths = sorted((DATA / "serving" / str(year)).glob("votos_*.parquet"))
    return combine_sources({p.stem.removeprefix("votos_"): pl.read_parquet(p) for p in paths})[0]

@st.cache_data(show_spinner=False)
def load_geometry(path, stamp):
    geo = gpd.read_file(path)
    if geo.crs is None:
        raise ValueError("Geometria sem CRS.")
    return geo.to_crs(4326)

@st.cache_data(show_spinner=False)
def crosswalk(stamp):
    table = pl.read_csv(DATA / "reference" / "tse_ibge.csv", infer_schema=False)
    keys = ["uf", "cd_municipio_tse", "codigo_ibge"]
    unique = table.select(keys).unique()
    if unique.group_by(keys[:2]).len().filter(pl.col("len") > 1).height:
        raise ValueError("Correspondência IBGE ambígua.")
    return unique

def georeference(data, level, uf):
    if level == "Município":
        path = DATA / "geo" / "municipios.geojson"
        ref = DATA / "reference" / "tse_ibge.csv"
        if not path.exists() or not ref.exists():
            raise ValueError("Malha municipal ou correspondência TSE/IBGE indisponível.")
        rows = data.join(crosswalk(ref.stat().st_mtime_ns), on=["uf", "cd_municipio_tse"], how="left")
        values = {str(x["codigo_ibge"]).zfill(7): x for x in rows.to_dicts() if x["codigo_ibge"]}
        geo = load_geometry(str(path), path.stat().st_mtime_ns).copy()
        field = next((name for name in ("codigo_ibge", "CD_MUN", "CD_GEOCMU") if name in geo), None)
        if not field:
            raise ValueError("Malha sem código IBGE.")
        geo["_key"] = [str(x).zfill(7) for x in geo[field]]
        if uf != "Todas":
            prefix = UF_PREFIX[uf]
            geo = geo.loc[[key.startswith(prefix) for key in geo["_key"]]].copy()
    else:
        path = zone_file(DATA, uf)
        if not path.exists():
            raise ValueError("Zonas aproximadas ausentes para a UF.")
        geo = load_geometry(str(path), path.stat().st_mtime_ns).copy()
        geo["_key"] = [f"{a}:{b}:{int(c)}" for a,b,c in zip(geo["uf"], geo["cd_municipio_tse"], geo["zona"])]
        values = {f'{r["uf"]}:{r["cd_municipio_tse"]}:{int(r["zona"])}': r for r in data.to_dicts()}
    # Mantém todos os contornos do recorte, inclusive regiões sem delta.
    # É essencial no filtro "Somente viradas": as demais divisas continuam no mapa.
    geo = geo.loc[geo.geometry.notna() & ~geo.geometry.is_empty].copy()
    geo["_vote"] = [values.get(key) for key in geo["_key"]]
    return geo

st.title("↗ Deltas e viradas de votos")
st.caption("Saldo = Lula (13) − Flávio (22) | Δ = saldo 2º turno − saldo 1º turno")
st.caption("A comparação de totais agregados não demonstra transferência individual de eleitores.")
years = sorted(
    (int(folder.name) for folder in (DATA / "serving").glob("20[0-9][0-9]")
     if (folder / "catalog.json").is_file()),
    reverse=True,
)
if not years:
    st.info("Sem dados eleitorais preparados.")
    st.stop()

with st.sidebar:
    year = st.selectbox("Eleição", years)
    paths = sorted((DATA / "serving" / str(year)).glob("votos_*.parquet"))
    votes = read_votes(year, tuple((p.name, p.stat().st_mtime_ns) for p in paths))
    votes = votes.filter(pl.col("cargo").str.to_lowercase() == "presidente")
    if votes.is_empty():
        st.info("Sem votação presidencial.")
        st.stop()
    states = sorted(votes["uf"].unique().to_list())
    uf = st.selectbox("UF", ["Todas"] + states)
    if uf != "Todas":
        votes = votes.filter(pl.col("uf") == uf)
    only_flips = st.checkbox("Somente viradas efetivas", value=False)

try:
    municipal_all = swing_results(votes, level="municipio")
except ValueError as exc:
    st.info(str(exc))
    st.stop()
if municipal_all.is_empty():
    st.info("Não há municípios com dois turnos comparáveis neste recorte.")
    st.stop()

state_all = state_swing_results(municipal_all)
state_view = state_all
municipal_view = municipal_all
if only_flips:
    municipal_view = municipal_all.filter(pl.col("virada") != "Sem virada")
    state_view = state_all.filter(pl.col("virada") != "Sem virada")

# Nunca carregar todas as áreas de zona do Brasil em uma única navegação:
# o TSE/IBGE gera malhas aproximadas por UF, potencialmente enormes.
zone_view = None
zone_geo = None
zone_ready = uf != "Todas" and zone_file(DATA, uf).is_file()
if zone_ready:
    try:
        zone_all = swing_results(votes, level="zona")
        zone_view = (zone_all.filter(pl.col("virada") != "Sem virada")
                     if only_flips else zone_all)
        if not zone_view.is_empty():
            zone_geo = georeference(zone_view, "Zona no município (aproximada)", uf)
    except (ValueError, KeyError, pl.exceptions.PolarsError) as exc:
        st.caption(f"Detalhamento por zona indisponível nesta UF: {exc}")

m1, m2, m3 = st.columns(3)
m1.metric("Δ favorável a Lula · municípios",
          municipal_view.filter(pl.col("delta") > 0).height)
m2.metric("Δ favorável a Flávio · municípios",
          municipal_view.filter(pl.col("delta") < 0).height)
m3.metric("Viradas efetivas · municípios",
          municipal_all.filter(pl.col("virada") != "Sem virada").height)

st.caption(
    "Setas automáticas pelo zoom: até 6, uma seta por UF; 7–10, municípios; "
    "a partir de 11, zonas eleitorais aproximadas quando preparadas."
)
st.caption(
    "No canto superior direito, alterne entre Divisões + setas e "
    "Áreas por delta (sem setas). As cores são 🔴 13/Lula e 🔵 22/Flávio."
)
try:
    municipal_geo = georeference(municipal_view, "Município", uf)
    if municipal_geo.empty:
        st.info("Não há malha municipal para este recorte.")
    else:
        map_view = delta_map(
            municipal_geo, states=state_view.to_dicts(),
            zones=zone_geo if zone_geo is not None and not zone_geo.empty else None,
        )
        st_folium(
            map_view, height=700, use_container_width=True,
            returned_objects=[],
            key=f"delta_zoom_{year}_{uf}_{only_flips}_{zone_ready}",
        )
        matched = sum(record is not None for record in municipal_geo["_vote"])
        if matched < municipal_view.height:
            st.caption(f"{municipal_view.height - matched} municípios sem geometria correspondente.")
except (ValueError, KeyError, OSError, pl.exceptions.PolarsError) as exc:
    st.info(f"Mapa indisponível: {exc}")

if uf == "Todas":
    st.caption(
        "Para ver as setas e áreas de zonas no zoom máximo, selecione uma UF. "
        "O mapa nacional não carrega simultaneamente todas as geometrias zonais."
    )
elif not zone_ready:
    st.caption(
        f"As áreas de zona de {uf} não estão preparadas; "
        "no zoom máximo permanecem as setas municipais."
    )
else:
    st.caption(
        "Zonas eleitorais: áreas APROXIMADAS a partir de setores IBGE 2022 "
        "e locais TSE, não limites oficiais."
    )
st.caption(
    "Uma seta estadual representa a soma dos saldos dos municípios com ambos "
    "os turnos comparáveis, não uma totalização oficial quando há cobertura parcial. "
    "A seta mostra variação relativa; virada efetiva exige troca do sinal do saldo."
)

st.subheader("Saldos e variações")
table_options = ["Município", "Estado"]
if zone_view is not None:
    table_options.append("Zona no município (aproximada)")
table_level = st.selectbox("Detalhamento da tabela", table_options)
selection = {
    "Município": municipal_view,
    "Estado": state_view,
    "Zona no município (aproximada)": zone_view,
}[table_level]
if selection is None or selection.is_empty():
    st.info("Sem regiões correspondentes ao filtro.")
else:
    st.dataframe(selection, width="stretch", hide_index=True)
    st.download_button(
        "Exportar CSV", selection.write_csv().encode("utf-8-sig"),
        file_name=f"deltas_{year}_{uf}_{table_level.split()[0]}.csv",
        mime="text/csv",
    )
