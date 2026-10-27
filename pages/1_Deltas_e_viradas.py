"""Página de deltas e viradas independente da apuração existente."""
from pathlib import Path
import folium
import geopandas as gpd
import polars as pl
import streamlit as st
from streamlit_folium import st_folium
from mapa_eleicoes.map_tiles import atlas_map
from mapa_eleicoes.swing import swing_results
from mapa_eleicoes.vote_sources import combine_sources
from mapa_eleicoes.zone_geometry import zone_file
from mapa_eleicoes.party_colors import PT_RED, PL_BLUE

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
    else:
        path = zone_file(DATA, uf)
        if not path.exists():
            raise ValueError("Zonas aproximadas ausentes para a UF.")
        geo = load_geometry(str(path), path.stat().st_mtime_ns).copy()
        geo["_key"] = [f"{a}:{b}:{int(c)}" for a,b,c in zip(geo["uf"], geo["cd_municipio_tse"], geo["zona"])]
        values = {f'{r["uf"]}:{r["cd_municipio_tse"]}:{int(r["zona"])}': r for r in data.to_dicts()}
    geo = geo.loc[geo["_key"].isin(values)].copy()
    geo["_vote"] = [values[key] for key in geo["_key"]]
    return geo

def delta_map(geo, arrows):
    bounds = geo.total_bounds
    m = atlas_map([(bounds[1]+bounds[3])/2, (bounds[0]+bounds[2])/2])
    features = []
    for _, item in geo.iterrows():
        r = item["_vote"]
        d = int(r["delta"])
        color = PT_RED if d > 0 else PL_BLUE if d < 0 else "#6272a4"
        caption = (f'{r["municipio"]} | Δ saldo: {d:+,} votos | '
                   f'Saldo 1T: {int(r["saldo_1t"]):+,} | Saldo 2T: {int(r["saldo_2t"]):+,} | '
                   f'Δ Lula: {int(r["delta_a"]):+,} | Δ Flávio: {int(r["delta_b"]):+,} | '
                   f'Virada: {r["virada"]}')
        features.append({"type":"Feature", "geometry": item.geometry.__geo_interface__,
                         "properties":{"color":color,"tooltip":caption}})
    folium.GeoJson({"type":"FeatureCollection","features":features},
                   style_function=lambda f: {"fillColor":f["properties"]["color"],"fillOpacity":.65,"color":"#161717","weight":.45},
                   tooltip=folium.GeoJsonTooltip(fields=["tooltip"],aliases=[""],labels=False)).add_to(m)
    if arrows:
        maximum = max((abs(int(r["delta"])) for r in geo["_vote"]), default=1) or 1
        for _, item in geo.iterrows():
            d = int(item["_vote"]["delta"])
            if not d or item.geometry is None or item.geometry.is_empty:
                continue
            p = item.geometry.representative_point()
            size = .01 + .1 * (abs(d)/maximum)**.5
            dest = [p.y + size, p.x + (-size if d > 0 else size)]
            color = PT_RED if d > 0 else PL_BLUE
            folium.PolyLine([[p.y,p.x],dest],color=color,weight=2.5,
                            tooltip=f"Δ saldo {d:+,}").add_to(m)
            folium.Marker(dest, icon=folium.DivIcon(
                html=f'<span style="color:{color};font-size:16px">{"↖" if d>0 else "↗"}</span>',
                icon_size=(18,18),icon_anchor=(9,9))).add_to(m)
    m.fit_bounds([[bounds[1],bounds[0]],[bounds[3],bounds[2]]])
    return m

st.title("↗ Deltas e viradas de votos")
st.caption("Saldo = Lula (13) − Flávio (22) | Δ = saldo 2º turno − saldo 1º turno")
st.caption("A comparação de totais agregados não prova transferência individual de votos.")
years = sorted([int(d.name) for d in (DATA/"serving").glob("20[0-9][0-9]") if (d/"catalog.json").exists()],reverse=True)
if not years:
    st.info("Sem dados eleitorais preparados.")
    st.stop()
with st.sidebar:
    year = st.selectbox("Eleição",years)
    paths = sorted((DATA/"serving"/str(year)).glob("votos_*.parquet"))
    votes = read_votes(year,tuple((p.name,p.stat().st_mtime_ns) for p in paths))
    votes = votes.filter(pl.col("cargo").str.to_lowercase()=="presidente")
    if votes.is_empty():
        st.info("Sem votação presidencial.")
        st.stop()
    states = sorted(votes["uf"].unique().to_list())
    uf = st.selectbox("UF",["Todas"]+states)
    if uf != "Todas":
        votes = votes.filter(pl.col("uf")==uf)
    level = st.radio("Detalhamento",["Município","Zona no município (aproximada)"])
    arrows = st.checkbox("Setas de variação",value=True)
    only_flips = st.checkbox("Somente viradas efetivas",value=False)
try:
    result = swing_results(votes,level="zona" if level != "Município" else "municipio")
except ValueError as exc:
    st.info(str(exc))
    st.stop()
if only_flips:
    result = result.filter(pl.col("virada")!="Sem virada")
if result.is_empty():
    st.info("Nenhum recorte com dados comparáveis para ambos os turnos.")
    st.stop()
m1,m2,m3 = st.columns(3)
m1.metric("Δ favorável a Lula",result.filter(pl.col("delta")>0).height)
m2.metric("Δ favorável a Flávio",result.filter(pl.col("delta")<0).height)
m3.metric("Viradas efetivas",result.filter(pl.col("virada")!="Sem virada").height)
st.caption("🔴 Vermelho / ↖: delta positivo · 🔵 Azul / ↗: delta negativo. Setas esquemáticas com tamanhos relativos dentro do recorte.")
if level != "Município" and uf == "Todas":
    st.info("Selecione uma UF para mapear áreas aproximadas de zona. A tabela permanece disponível.")
else:
    try:
        geo = georeference(result,level,uf)
        if geo.empty:
            st.info("Não há geometria disponível para os resultados selecionados.")
        else:
            st_folium(delta_map(geo,arrows),height=700,use_container_width=True,
                      returned_objects=[],key=f"delta_{year}_{uf}_{level}_{arrows}_{only_flips}")
            if level != "Município":
                st.caption("Geometria aproximada (setores IBGE 2022 + locais TSE), NÃO é limite oficial de zona.")
            if geo.shape[0] < result.height:
                st.caption(f"{result.height-geo.shape[0]} unidades sem geometria correspondente.")
    except (ValueError,KeyError,OSError) as exc:
        st.info(f"Mapa indisponível: {exc}")
st.subheader("Saldos e variações")
st.dataframe(result,width="stretch",hide_index=True)
st.download_button("Exportar CSV",result.write_csv().encode("utf-8-sig"),
                   file_name=f"deltas_{year}_{uf}.csv",mime="text/csv")
