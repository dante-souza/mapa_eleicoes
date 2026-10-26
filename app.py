"""Painel Atlas Eleitoral. Entrada operacional: make run."""
from __future__ import annotations

import json
from pathlib import Path

import folium
import geopandas as gpd
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
COLORS = ['#ff5555', '#6272a4', '#bd93f9', '#50fa7b', '#ffb86c', '#8be9fd', '#f1fa8c', '#ff79c6']

st.set_page_config(page_title='Atlas Eleitoral', page_icon='🗳️', layout='wide')
st.markdown('''<style>
[data-testid="stAppViewContainer"] {background:#191923;color:#f8f8f2}
[data-testid="stSidebar"] {background:#252536}
[data-testid="stMetric"] {background:#282a36;border:1px solid #44475a;border-radius:10px;padding:14px}
.block-container {max-width:1750px;padding-top:1.2rem}
</style>''', unsafe_allow_html=True)

@st.cache_data(show_spinner=False)
def load_votes(year: int) -> pd.DataFrame:
    files = sorted((DATA/'processed'/str(year)).glob('votos_*.csv.gz'))
    if not files: return pd.DataFrame()
    out = pd.concat((pd.read_csv(file, dtype={'cd_municipio_tse':str,'numero':str,'uf':str}) for file in files), ignore_index=True)
    for col in ('ano','turno','zona','votos'): out[col] = pd.to_numeric(out[col])
    for col in ('uf','cd_municipio_tse','municipio','numero','candidato','cargo','tipo_voto'):
        out[col] = out[col].astype(str)
    return out

@st.cache_data(show_spinner=False)
def load_shape(level: str):
    filename = 'zonas.geojson' if level == 'Zona eleitoral' else 'municipios.geojson'
    file = DATA/'geo'/filename
    if not file.exists(): return None
    gdf = gpd.read_file(file)
    if gdf.crs is None: raise ValueError('GeoJSON sem CRS')
    return gdf.to_crs(4326)

@st.cache_data(show_spinner=False)
def crosswalk():
    file = DATA/'reference'/'tse_ibge.csv'
    if not file.exists(): return None
    return pd.read_csv(file, dtype=str).fillna('')


def field(gdf, candidates):
    return next((x for x in candidates if x in gdf.columns), None)


def shape_for_votes(gdf, votes, level):
    """Join por codigo numerico, sem aproximações espaciais inventadas."""
    if level == 'Zona eleitoral':
        uf_col = field(gdf, ['UF','uf','SG_UF','sg_uf'])
        zona_col = field(gdf, ['NR_ZONA','nr_zona','zona','ZONA'])
        if not uf_col or not zona_col:
            raise ValueError('Malha de zonas precisa de UF e NR_ZONA nas propriedades.')
        gdf = gdf.copy()
        gdf['map_id'] = gdf[uf_col].astype(str).str.upper() + ':' + pd.to_numeric(gdf[zona_col], errors='coerce').astype('Int64').astype(str)
        votes = votes.copy()
        votes['map_id'] = votes['uf'] + ':' + votes['zona'].astype(str)
    else:
        xwalk = crosswalk()
        if xwalk is None:
            raise ValueError('Falta data/reference/tse_ibge.csv; importe o de/para oficial (make crosswalk).')
        keys = ['uf','cd_municipio_tse','codigo_ibge']
        needed = set(keys)
        if not needed.issubset(xwalk.columns): raise ValueError(f'De/para sem {needed - set(xwalk.columns)}')
        xwalk = xwalk[keys].drop_duplicates(subset=['uf','cd_municipio_tse'])
        votes = votes.merge(xwalk, on=['uf','cd_municipio_tse'], how='left', validate='many_to_one')
        votes['map_id'] = votes['codigo_ibge'].fillna('')
        code_col = field(gdf,['CD_MUN','CD_GEOCMU','codarea','codigo_ibge','code_muni','id','CD_MUN_IBGE'])
        if not code_col:
            raise ValueError('Malha municipal sem codigo IBGE (7 dígitos); nome não é chave confiável.')
        gdf = gdf.copy()
        gdf['map_id'] = gdf[code_col].astype(str).str.replace(r'\.0$', '', regex=True)
    return gdf, votes


def winner_table(frame: pd.DataFrame) -> pd.DataFrame:
    nominal = frame[frame['tipo_voto'] == 'nominal']
    grouped = nominal.groupby(['map_id','numero','candidato'], as_index=False)['votos'].sum()
    if grouped.empty: return grouped
    grouped['total_validos'] = grouped.groupby('map_id')['votos'].transform('sum')
    grouped['pct'] = 100 * grouped['votos'] / grouped['total_validos']
    grouped = grouped.sort_values(['map_id','votos','numero'], ascending=[True,False,True])
    return grouped.groupby('map_id', as_index=False).first()


def draw_map(geometry: gpd.GeoDataFrame, data: pd.DataFrame, mode: str, selected: str | None, level: str):
    winners = winner_table(data)
    if winners.empty:
        st.info('Não há votos nominais para criar o mapa.'); return
    colors = {name: COLORS[i % len(COLORS)] for i, name in enumerate(
        data[data.tipo_voto == 'nominal'].groupby('candidato')['votos'].sum().sort_values(ascending=False).index)}
    if mode == 'Votação de candidato' and selected:
        cand = data[(data.tipo_voto == 'nominal') & (data.candidato == selected)].groupby('map_id')['votos'].sum()
        winners['votos_candidato'] = winners['map_id'].map(cand).fillna(0).astype('int64')
        winners['percentual_candidato'] = 100 * winners['votos_candidato'] / winners['total_validos']
    merged = geometry.merge(winners, on='map_id', how='left')
    merged = merged[merged['map_id'].isin(set(data['map_id'])) & merged.geometry.notna()].copy()
    if merged.empty:
        st.warning('Não foi possível associar os dados à malha. Verifique as chaves geográficas.');return
    region_data = merged[['map_id','candidato','numero','votos','pct']].copy()
    region_data['candidato'] = region_data['candidato'].fillna('Sem dados')
    if mode == 'Votação de candidato' and selected:
        region_data['destaque'] = merged['percentual_candidato'].round(2)
    display = merged[['map_id','geometry']].copy()
    display['nome_tooltip'] = region_data['map_id']
    display['vencedor'] = region_data['candidato'].astype(str)
    display['votos_vencedor'] = region_data['votos'].fillna(0).astype('int64')
    display['percentual_vencedor'] = region_data['pct'].fillna(0).round(2)
    if mode == 'Votação de candidato' and selected:
        display['destaque'] = merged['percentual_candidato'].fillna(0).round(2)
    geojson = json.loads(display.to_json(drop_id=True))
    palette = {str(k): str(colors.get(k, '#44475a')) for k in colors}
    color_by_key = {row.map_id: palette.get(row.candidato,'#44475a') for row in region_data.itertuples()}
    highlight = {row.map_id: float(getattr(row,'destaque',0)) for row in region_data.itertuples()}
    # Fundo claro neutro, sem depender de tokens de serviços externos.
    center = merged.geometry.union_all().representative_point()
    bounds = merged.total_bounds  # minx miny maxx maxy
    fmap = folium.Map(location=[float(center.y), float(center.x)], zoom_start=5,
                      tiles='CartoDB dark_matter', control_scale=True, prefer_canvas=True)
    def style(feature):
        k = feature['properties']['map_id']
        intensity = min(1.0, max(.05, highlight.get(k, 0) / 100))
        return {'fillColor': colors.get(selected,'#ff5555') if mode == 'Votação de candidato' else color_by_key.get(k,'#44475a'),
                'fillOpacity': .15 + .80*intensity if mode == 'Votação de candidato' else .78,
                'color':'#11111b','weight':.45}
    tooltip_fields = ['nome_tooltip','vencedor','votos_vencedor','percentual_vencedor']
    aliases = ['Código geográfico','Mais votado','Votos do líder','% dos válidos']
    if mode == 'Votação de candidato':
        tooltip_fields += ['destaque'];aliases += ['% do candidato']
    folium.GeoJson(geojson, name='Resultados', style_function=style,
                   highlight_function=lambda _: {'weight':1.5,'color':'#f8f8f2'},
                   tooltip=folium.GeoJsonTooltip(fields=tooltip_fields, aliases=aliases, sticky=False)).add_to(fmap)
    fmap.fit_bounds([[bounds[1],bounds[0]], [bounds[3],bounds[2]]])
    st_folium(fmap, height=700, returned_objects=[], use_container_width=True)
    st.caption(f'{len(display)} polígonos exibidos • Geometria: {level} • Sem inferir áreas eleitorais inexistentes')


st.title('🗳️ Atlas Eleitoral')
st.caption('Dados públicos do Tribunal Superior Eleitoral · Estudo independente · Sem vínculo com TSE ou G1')
years = sorted((int(p.name) for p in (DATA/'processed').glob('20[0-9][0-9]') if p.is_dir()), reverse=True)
if not years:
    st.warning('Sem dados processados. Use `make import FILE=...` e `make ingest` para habilitar o painel.')
    st.stop()
with st.sidebar:
    year = st.selectbox('Eleição', years)
    votes = load_votes(year)
    if votes.empty:
        st.error('Ano sem arquivos Parquet.');st.stop()
    uf_opts = sorted(votes.uf.dropna().unique())
    uf = st.selectbox('UF', ['Todas'] + uf_opts)
    if uf != 'Todas': votes = votes[votes.uf == uf]
    turno = st.selectbox('Turno', sorted(votes.turno.unique()), index=0)
    votes = votes[votes.turno == turno]
    cargo = st.selectbox('Cargo', sorted(votes.cargo.unique()))
    votes = votes[votes.cargo == cargo]
    municipality = st.selectbox('Município', ['Todos'] + sorted(votes.municipio.unique()))
    if municipality != 'Todos': votes = votes[votes.municipio == municipality]
    zona = st.selectbox('Zona', ['Todas'] + sorted(votes.zona.unique().tolist(), key=int))
    if zona != 'Todas': votes = votes[votes.zona == zona]
    level = st.radio('Geometria', ['Município','Zona eleitoral'], help='A segunda opção exige polígonos reais das zonas.')
    if level == 'Município' and zona != 'Todas':
        st.warning('Mapa municipal com filtro de zona: o polígono é o município inteiro, NÃO a área geográfica da zona selecionada.')
    mode = st.radio('Visualização', ['Vencedor por região','Votação de candidato'])
    total_per_candidate = votes[votes.tipo_voto == 'nominal'].groupby('candidato')['votos'].sum().sort_values(ascending=False)
    candidate = st.selectbox('Candidato', total_per_candidate.index.to_list()) if mode == 'Votação de candidato' and len(total_per_candidate) else None

validos = votes.loc[votes.tipo_voto=='nominal','votos'].sum()
brancos = votes.loc[votes.tipo_voto=='branco','votos'].sum()
nulos = votes.loc[votes.tipo_voto=='nulo','votos'].sum()
m1,m2,m3,m4 = st.columns(4)
m1.metric('Votos nominais',f'{int(validos):,}'.replace(',','.'))
m2.metric('Brancos',f'{int(brancos):,}'.replace(',','.'))
m3.metric('Nulos',f'{int(nulos):,}'.replace(',','.'))
m4.metric('Zonas representadas',votes[['uf','zona']].drop_duplicates().shape[0])

left,right = st.columns([3,1], gap='large')
with left:
    polygons = load_shape(level)
    if polygons is None:
        st.warning(f'Sem malha geográfica de {level.lower()}. Importe um GeoJSON/GPKG/SHP ZIP pelo alvo `make geo-import`. Os dados e tabelas permanecem disponíveis.')
    else:
        try:
            boundaries, scoped = shape_for_votes(polygons, votes, level)
            matched = scoped[scoped.map_id.notna() & (scoped.map_id != '')]
            if len(matched) < len(scoped):
                st.info(f'{len(scoped)-len(matched)} linhas sem correspondência geográfica (não interpoladas).')
            draw_map(boundaries, matched, mode, candidate, level)
        except (ValueError, KeyError) as exc:
            st.error(f'Mapa indisponível: {exc}')
with right:
    st.subheader(f'{cargo} · {turno}º turno')
    total = total_per_candidate.sum()
    for name, count in total_per_candidate.head(12).items():
        pct = 100 * count / total if total else 0
        st.markdown(f'**{name}** — {int(count):,} votos · {pct:.2f}%')
        st.progress(min(1.0,pct/100))
    st.caption(f'{len(uf_opts)} UFs no conjunto processado · cobertura parcial caso não haja arquivos para todo o país')

st.subheader('Detalhamento por zona eleitoral')
table = votes.groupby(['uf','municipio','zona','cargo','numero','candidato','tipo_voto'],as_index=False)['votos'].sum()
st.dataframe(table.sort_values('votos',ascending=False), use_container_width=True, hide_index=True)
st.download_button('Exportar seleção CSV', table.to_csv(index=False).encode('utf-8-sig'),
                   file_name=f'atlas_{year}_turno{turno}.csv',mime='text/csv')