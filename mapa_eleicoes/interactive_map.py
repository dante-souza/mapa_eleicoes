"""Explorador Leaflet: municipios sempre visiveis, detalhes por zoom.

Pan, zoom e hover NAO voltam ao Streamlit. O componente devolve apenas o
clique; cada zoom/arrasto que voltava ao servidor disparava um rerun, que
apagava a pagina (overlay cinza), redesenhava o mapa e devolvia a camera
antiga, num ciclo. Agora:

- tooltips de municipio, zona e local rodam no navegador;
- zonas e locais ficam em panes que aparecem pelo zoom no navegador
  (mapa_eleicoes.map_panes): municipio -> zona -> local, sem rerun;
- o clique num municipio enquadra e destaca a cidade no navegador
  (mapa_eleicoes.map_focus) e faz UM rerun (callback on_change do
  componente) so para carregar os locais daquela cidade. No modo "Zona
  eleitoral (aproximada)", o clique seleciona a zona, como no g1.

O mapa base so muda quando os filtros mudam; entao o componente nao e
remontado entre cliques. Nenhum poligono de secao e inventado.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import folium
import geopandas as gpd
import polars as pl
import streamlit as st
from streamlit_folium import st_folium

from mapa_eleicoes.map_navigation import (
    municipality_at, state_for_municipality, valid_position,
)
from mapa_eleicoes.map_panes import (
    DISTRICT_PANE, SITE_PANE, ZONE_PANE, ClusterAssets, ZoomPanes, explorer_gates,
)
from mapa_eleicoes.section_map import (
    load_locations, load_sections, section_detail, site_feature_group,
)
from mapa_eleicoes.zone_geometry import district_file, zone_file
from mapa_eleicoes.zone_names import load_zone_labels
from mapa_eleicoes.zone_map import (
    district_layer, load_districts, load_zone_areas, zone_at, zone_layer,
)

ZONE_DETAIL = "Zona eleitoral (aproximada)"
SITE_DETAIL = "Seção eleitoral (locais)"
PENDING_ZONE = "atlas_pending_zone"
MAP_HEIGHT = 700


@st.cache_data(show_spinner=False)
def _zone_areas(root: str, uf: str, stamp: float) -> gpd.GeoDataFrame | None:
    """Cache por UF; `stamp` (mtime) invalida apos novo make zones-setup."""
    return load_zone_areas(Path(root), uf)


@st.cache_data(show_spinner=False)
def zone_label_maps(root: str, year: int, stamp: float) -> tuple[dict[str, str], dict[str, str]]:
    """Nomes aproximados das zonas; `stamp` (mtime de locais.parquet) invalida."""
    return load_zone_labels(Path(root), year)


def cached_zone_labels(root: Path, year: int) -> tuple[dict[str, str], dict[str, str]]:
    path = root / "serving" / str(year) / "locais.parquet"
    if not path.is_file():
        return {}, {}
    return zone_label_maps(str(root), year, path.stat().st_mtime)


@st.cache_data(show_spinner=False)
def _districts(root: str, uf: str, stamp: float) -> gpd.GeoDataFrame | None:
    return load_districts(Path(root), uf)


def _cached(loader, path: Path, root: Path, uf: str) -> gpd.GeoDataFrame | None:
    if not path.is_file():
        return None
    return loader(str(root), uf, path.stat().st_mtime)


def _names(votes: pl.DataFrame | None) -> dict[str, str]:
    if votes is None or votes.is_empty():
        return {}
    return {
        f"{row['uf']}:{row['cd_municipio_tse']}": row["municipio"]
        for row in votes.select(["uf", "cd_municipio_tse", "municipio"])
        .unique(subset=["uf", "cd_municipio_tse"]).iter_rows(named=True)
    }


def render_explorer(
    base_map: folium.Map,
    municipal_shapes: gpd.GeoDataFrame,
    crosswalk: pl.DataFrame | None,
    *,
    root: Path,
    year: int,
    uf: str,
    cargo: str,
    turno: int,
    municipio: str,
    zona: int | str,
    mode: str,
    candidate_number: str | None,
    detail: str,
    section_ready: bool,
    zone_votes: pl.DataFrame | None = None,
    district_votes: pl.DataFrame | None = None,
) -> None:
    """Desenha o mapa e trata o clique; nenhum outro evento volta ao servidor.

    zone_votes: votos do recorte SEM o filtro de zona (zonas da cidade).
    district_votes: votos da UF inteira SEM filtro de municipio/zona
    (a zona inteira soma todos os seus municipios).
    """
    scope = (year, uf, cargo, turno, municipio, str(zona), mode, detail)
    if st.session_state.get("atlas_explorer_scope") != scope:
        st.session_state["atlas_explorer_scope"] = scope
        st.session_state["atlas_explorer_focus"] = None
        st.session_state["atlas_explorer_last_click"] = None
    focus = st.session_state.get("atlas_explorer_focus")
    pending_zone_before = st.session_state.get(PENDING_ZONE)
    selected = candidate_number if mode == "Votação de candidato" else None
    highlight = None if zona == "Todas" else int(zona)
    cities = set(str(code) for code in municipal_shapes["map_id"])
    if municipio != "Todos" and len(cities) == 1:
        # Municipio escolhido no seletor: o mapa ja enquadra a cidade.
        city = next(iter(cities))
    else:
        city = focus["city"] if focus else None

    # "Município": so a malha municipal, sem camadas de detalhe.
    drill = detail != "Município"
    # O Atlas opera apenas em Automático: não existe mais modo de
    # zona em tela separada. Os panes são controlados pelo zoom.
    district_mode = False
    # Sempre iniciar o mapa com os panes do fluxo automatico.
    base_map.add_child(ZoomPanes(explorer_gates("Automático")))
    if section_ready:
        base_map.add_child(ClusterAssets())

    zone_count = 0
    districts = None
    dynamic: list[folium.FeatureGroup] = []
    names = _names(district_votes if district_mode else zone_votes)
    labels = cached_zone_labels(root, year)
    try:
        if district_mode:
            districts = _cached(_districts, district_file(root, uf), root, uf)
            if districts is None:
                st.caption("As zonas aproximadas desta UF ainda não foram preparadas.")
            else:
                group, zone_count = district_layer(
                    districts, district_votes if district_votes is not None
                    else pl.DataFrame(),
                    names=names, selected_number=selected,
                    highlight_zone=highlight, pane=DISTRICT_PANE, labels=labels,
                )
                if group is not None:
                    base_map.add_child(group)
        elif drill and zone_votes is not None and not zone_votes.is_empty():
            # Com UF escolhida, todas as cidades com varias zonas vao no mapa
            # base (aparecem pelo zoom). Sem UF, so a cidade clicada.
            target_uf = uf if uf != "Todas" else state_for_municipality(city)
            areas = (
                _cached(_zone_areas, zone_file(root, target_uf), root, target_uf)
                if target_uf else None
            )
            if areas is not None and not areas.empty:
                # Priorizar o município focado independentemente da UF:
                # a camada estadual completa pode exceder MAX_ZONE_AREAS
                # e truncar justamente as zonas do município clicado.
                wanted = {city} if city else (cities if uf != "Todas" else set())
                areas = areas.loc[[str(code) in wanted for code in areas["codigo_ibge"]]]
                group, zone_count = zone_layer(
                    areas, zone_votes.filter(pl.col("uf") == target_uf),
                    names=names, selected_number=selected,
                    highlight_zone=highlight, pane=ZONE_PANE, labels=labels,
                )
                if group is not None:
                    # Na navegacao nacional, após clicar em uma cidade,
                    # o Streamlit reconstroi o mapa com esta camada NO
                    # GeoJSON inicial. Não depender de feature_group_to_add
                    # para zonas (a ponte pode montar a pane tarde demais).
                    # A visibilidade permanece controlada no navegador.
                    base_map.add_child(group)
    except (ValueError, KeyError, OSError, pl.exceptions.PolarsError):
        zone_count = 0
        st.caption("As zonas desta área estão indisponíveis; os municípios continuam no mapa.")

    report = None
    if drill and city and section_ready and crosswalk is not None:
        report = _site_layer(
            dynamic, root=root, year=year, city=city, crosswalk=crosswalk,
            cargo=cargo, turno=turno, zona=zona, selected=selected,
        )

    key_suffix = hashlib.sha256(repr(scope).encode("utf-8")).hexdigest()[:16]
    map_key = f"atlas_explorer_{key_suffix}"

    def on_map_change() -> None:
        # A API streamlit-folium pode executar o callback ao montar o
        # componente: o mapa atual talvez já tenha sido construído antes
        # de atualizar o focus. Abaixo haverá um rerun APENAS se necessário.
        _handle_click(
            st.session_state.get(map_key), municipal_shapes,
            districts if district_mode else None,
            zona=zona, current_city=city,
        )

    st_folium(
        base_map,
        key=map_key,
        on_change=on_map_change,
        height=MAP_HEIGHT,
        use_container_width=True,
        # Só eventos de clique voltam para o servidor, nunca zoom/centro.
        # last_clicked cobre também Canvas/panes que não enviam
        # last_object_clicked em um clique de polígono.
        returned_objects=[
            "last_clicked", "last_object_clicked", "last_object_clicked_count",
        ],
        return_on_hover=False,
        feature_group_to_add=dynamic or None,
    )
    # Proteção para versões em que o callback do componente só é invocado
    # quando a execução alcança st_folium (após construir o Folium Map).
    # No máximo um rerun adicional por seleção nova; zoom/pan não dispara.
    if (st.session_state.get("atlas_explorer_focus") != focus
            or st.session_state.get(PENDING_ZONE) != pending_zone_before):
        st.rerun()
    if drill:
        _captions(zone_count, district_mode, report, city, detail, section_ready,
                  zones_on_zoom=uf != "Todas")
    else:
        st.caption("Passe o mouse sobre um município para ver os votos.")


def _site_layer(
    dynamic: list[folium.FeatureGroup], *, root: Path, year: int, city: str,
    crosswalk: pl.DataFrame, cargo: str, turno: int, zona: int | str,
    selected: str | None,
) -> dict | None:
    """Locais de votacao da cidade em foco, no pane que aparece pelo zoom."""
    state_code = state_for_municipality(city)
    if not state_code:
        return None
    codes = (
        crosswalk.filter(
            (pl.col("codigo_ibge") == city) & (pl.col("uf") == state_code)
        )["cd_municipio_tse"].unique().to_list()
    )
    if not codes:
        return None
    section_votes = load_sections(
        root, year, state_code, codes, cargo, turno,
        zona=None if zona == "Todas" else int(zona),
    )
    if section_votes.is_empty():
        return None
    try:
        locations = load_locations(root, year, state_code, codes, turno)
        rows, sites, no_location = section_detail(
            section_votes, locations, selected_number=selected,
        )
        if sites.is_empty():
            return None
        group, count, hidden = site_feature_group(
            rows, sites, selected_number=selected, pane=SITE_PANE,
        )
    except (ValueError, KeyError, pl.exceptions.PolarsError):
        # O mapa municipal continua disponível, mesmo que um
        # cadastro de locais contenha inconsistências.
        st.caption(
            "O detalhamento desta cidade está indisponível; "
            "os resultados municipais permanecem acessíveis."
        )
        return None
    dynamic.append(group)
    return {
        "city": city, "sites": count, "hidden": hidden,
        "sections": rows.height, "without_coordinates": no_location,
        "section_votes": section_votes,
    }


def _handle_click(
    response: dict | None, municipal_shapes: gpd.GeoDataFrame,
    districts: gpd.GeoDataFrame | None, *, zona: int | str,
    current_city: str | None,
) -> None:
    if not response:
        return
    # O frontend mantém a coordenada do clique anterior nos dois campos.
    # Se o Canvas atualizar só last_object_clicked, nunca reutilizar um
    # last_clicked antigo. Escolher o evento que MUDOU neste callback.
    previous = st.session_state.get("atlas_explorer_last_click")
    previous = previous if isinstance(previous, dict) else {}

    def coordinate_token(point: dict | None) -> tuple[float, float] | None:
        if not isinstance(point, dict):
            return None
        position = valid_position(point)
        return tuple(round(value, 6) for value in position) if position else None

    map_click = response.get("last_clicked")
    object_click = response.get("last_object_clicked")
    map_token = coordinate_token(map_click)
    object_token = coordinate_token(object_click)
    object_count = response.get("last_object_clicked_count")
    if map_token is not None and map_token != previous.get("map"):
        click = map_click
    elif object_token is not None and (
        object_token != previous.get("object")
        or object_count != previous.get("object_count")
    ):
        click = object_click
    else:
        return
    st.session_state["atlas_explorer_last_click"] = {
        "map": map_token, "object": object_token,
        "object_count": object_count,
    }
    if districts is not None:
        # Mapa por zona: o clique seleciona a zona (preenche o seletor).
        clicked_zone = zone_at(districts, click)
        if clicked_zone is not None and str(clicked_zone) != str(zona):
            st.session_state[PENDING_ZONE] = clicked_zone
        return
    city = municipality_at(municipal_shapes, click)
    if not city or city == current_city:
        return
    # Cidade em foco no servidor = de onde carregar os locais de votacao.
    st.session_state["atlas_explorer_focus"] = {"city": city}


def _captions(
    zone_count: int, district_mode: bool, report: dict | None,
    city: str | None, detail: str, section_ready: bool, *, zones_on_zoom: bool,
) -> None:
    if zone_count:
        what = (
            "zonas eleitorais nesta UF" if district_mode else
            "áreas de zona em cidades com mais de uma zona (aparecem ao aproximar)"
        )
        st.caption(
            f"{zone_count:,} {what}. Contornos aproximados: setores censitários "
            "IBGE 2022 atribuídos à zona com mais seções nos locais de votação "
            "do TSE; não são limites oficiais.".replace(",", ".")
        )
    if report:
        st.caption(
            f"Município {report['city']} · "
            f"{report['sites']:,} locais de votação · "
            f"{report['sections']:,} seções com ponto geográfico · "
            f"{report['without_coordinates']:,} sem coordenadas."
            .replace(",", ".")
        )
        if report["hidden"]:
            st.caption("Exibindo até 1.800 locais desta cidade.")
        with st.expander("Resultados individuais das seções deste município"):
            st.dataframe(report["section_votes"], width="stretch", hide_index=True)
    elif district_mode:
        st.caption(
            "Passe o mouse sobre uma zona para ver o resultado; clique para "
            "selecioná-la. Para ver os locais de votação, escolha um município."
        )
    elif detail == SITE_DETAIL and not city:
        st.caption("Clique num município para ver os locais de votação e as seções.")
    else:
        zones = (
            "Aproxime o mapa para ver as zonas eleitorais das cidades"
            if zones_on_zoom else
            "Clique num município para ver as zonas eleitorais dele"
        )
        st.caption(
            "Passe o mouse sobre um município para ver os votos. " + zones
            + ("; o clique também carrega os locais de votação, que aparecem "
               "ao aproximar mais." if section_ready else ".")
        )
