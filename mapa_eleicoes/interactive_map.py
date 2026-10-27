"""Explorador Leaflet: municipios sempre visiveis, detalhes por zoom.

Hover acontece inteiramente no browser via GeoJsonTooltip; servidor
recebe apenas zoom/centro e clique. No zoom urbano sao consultados
Parquets da UF e do municipio correspondente ao centro/ponteiro.
Nenhum poligono de secao e inventado.
"""
from __future__ import annotations

import hashlib
import folium
import geopandas as gpd
import polars as pl
import streamlit as st
from streamlit_folium import st_folium
from pathlib import Path

from mapa_eleicoes.map_navigation import (
    municipality_at, should_render_sites, state_for_municipality, FOCUS_ZOOM,
)
from mapa_eleicoes.section_map import (
    load_sections, load_locations, section_detail, site_feature_group,
)


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
) -> None:
    """Mantem o poligono mesmo quando ainda nao pode desenhar locais."""
    scope = (year, uf, cargo, turno, municipio, str(zona), mode, detail)
    if st.session_state.get("atlas_explorer_scope") != scope:
        st.session_state["atlas_explorer_scope"] = scope
        st.session_state["atlas_explorer_view"] = {}
        st.session_state["atlas_explorer_last_click"] = None
    camera = dict(st.session_state["atlas_explorer_view"])
    auto = detail in ("Automático", "Seção eleitoral (locais)")
    geojson_layer = None
    report = None
    city_code = None

    if auto and should_render_sites(camera.get("zoom"), section_ready):
        city_code = municipality_at(municipal_shapes, camera.get("center"))
        state_code = state_for_municipality(city_code)
        if city_code and state_code and crosswalk is not None:
            codes = (
                crosswalk.filter(
                    (pl.col("codigo_ibge") == city_code)
                    & (pl.col("uf") == state_code)
                )["cd_municipio_tse"].unique().to_list()
            )
            if codes:
                section_votes = load_sections(
                    root, year, state_code, codes, cargo, turno,
                    zona=None if zona == "Todas" else int(zona),
                )
                if not section_votes.is_empty():
                    locations = load_locations(
                        root, year, state_code, codes, turno
                    )
                    try:
                        rows, sites, no_location = section_detail(
                            section_votes, locations,
                            selected_number=candidate_number
                            if mode == "Votação de candidato" else None,
                        )
                        if not sites.is_empty():
                            geojson_layer, count, hidden = site_feature_group(
                                rows, sites,
                                selected_number=candidate_number
                                if mode == "Votação de candidato" else None,
                            )
                            report = {
                                "city": city_code, "sites": count,
                                "hidden": hidden, "sections": rows.height,
                                "without_coordinates": no_location,
                                "section_votes": section_votes,
                            }
                    except (ValueError, KeyError, pl.exceptions.PolarsError):
                        # O mapa municipal continua disponível, mesmo que um
                        # cadastro de locais contenha inconsistências.
                        st.caption(
                            "O detalhamento desta cidade está indisponível; "
                            "os resultados municipais permanecem acessíveis."
                        )

    key_suffix = hashlib.sha256(repr(scope).encode("utf-8")).hexdigest()[:16]
    response = st_folium(
        base_map,
        key=f"atlas_explorer_{key_suffix}",
        height=700,
        use_container_width=True,
        returned_objects=[
            "zoom", "center", "last_object_clicked",
            "last_object_clicked_count",
        ],
        return_on_hover=False,
        feature_group_to_add=geojson_layer,
        zoom=camera.get("zoom"),
        center=camera.get("center"),
    )
    if response:
        next_camera = dict(camera)
        zoom = response.get("zoom")
        if isinstance(zoom, (int, float)):
            next_camera["zoom"] = zoom
        center = response.get("center")
        if isinstance(center, dict) and {"lat", "lng"} <= set(center):
            next_camera["center"] = center

        click = response.get("last_object_clicked")
        if isinstance(click, dict) and {"lat", "lng"} <= set(click):
            token = (
                response.get("last_object_clicked_count"),
                round(float(click["lat"]), 6),
                round(float(click["lng"]), 6),
            )
            if token != st.session_state.get("atlas_explorer_last_click"):
                st.session_state["atlas_explorer_last_click"] = token
                if auto and municipality_at(municipal_shapes, click):
                    # O clique sobre municipio é equivalente ao zoom no
                    # mapa do G1. Coordenadas sao de onde o usuário clicou.
                    next_camera["center"] = click
                    next_camera["zoom"] = max(
                        float(next_camera.get("zoom") or 5), FOCUS_ZOOM
                    )
                    st.session_state["atlas_explorer_view"] = next_camera
                    st.rerun()
        st.session_state["atlas_explorer_view"] = next_camera

    if report:
        st.caption(
            f"Município {report['city']} · "
            f"{report['sites']:,} locais de votação · "
            f"{report['sections']:,} seções com ponto geográfico · "
            f"{report['without_coordinates']:,} sem coordenadas."
        )
        if report["hidden"]:
            st.caption(
                f"Exibindo até 1.800 locais; aproxime ou mova o mapa "
                f"para examinar outras áreas."
            )
        with st.expander("Resultados individuais das seções deste município"):
            st.dataframe(report["section_votes"], width="stretch", hide_index=True)
    else:
        st.caption(
            "Passe o mouse sobre um município para consultar os votos. "
            "Clique ou aproxime para revelar os locais de votação e as seções."
        )
