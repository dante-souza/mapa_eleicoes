"""Navegacao por mouse, clique e escala cartografica sem navegador."""
from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from mapa_eleicoes.map_navigation import (
    SITE_ZOOM, FOCUS_ZOOM, ZONE_ZOOM, municipality_at, should_render_sites,
    state_for_municipality, valid_position,
)


def geometry():
    return gpd.GeoDataFrame(
        {
            "map_id": ["3550308", "3304557"],
            "geometry": [
                Polygon([(-47, -24), (-46, -24), (-46, -23), (-47, -23)]),
                Polygon([(-44, -23), (-43, -23), (-43, -22), (-44, -22)]),
            ],
        },
        crs="EPSG:4326",
    )


def test_mouse_position_selects_real_municipal_polygon_only():
    shapes = geometry()
    assert municipality_at(shapes, {"lat": -23.5, "lng": -46.5}) == "3550308"
    assert municipality_at(shapes, {"lat": -22.5, "lng": -43.5}) == "3304557"
    assert municipality_at(shapes, {"lat": -20, "lng": -40}) is None
    assert municipality_at(shapes, {"lat": "x", "lng": -46}) is None


def test_edge_uses_polygon_covers_without_inventing_nearest_city():
    shapes = geometry()
    assert municipality_at(shapes, {"lat": -23.5, "lng": -46.0}) == "3550308"
    assert municipality_at(shapes, {"lat": -25, "lng": -46.5}) is None


def test_drilldown_order_municipio_zona_local():
    # Municipio -> zonas -> locais, cada nivel com mais zoom.
    assert ZONE_ZOOM <= FOCUS_ZOOM < SITE_ZOOM


def test_section_pins_appear_only_after_urban_zoom():
    assert not should_render_sites(5, True)
    assert not should_render_sites(SITE_ZOOM - 1, True)
    assert should_render_sites(SITE_ZOOM, True)
    assert should_render_sites(SITE_ZOOM + 2, True)
    assert not should_render_sites(SITE_ZOOM + 2, False)
    assert not should_render_sites(None, True)


def test_uf_derived_from_ibge_code_not_current_sidebar():
    assert state_for_municipality("3550308") == "SP"
    assert state_for_municipality("3304557") == "RJ"
    assert state_for_municipality("5300108") == "DF"
    assert state_for_municipality("random") is None


def test_invalid_mouse_payload_is_rejected():
    for wrong in (None, {}, {"lat": 100, "lng": 0},
                  {"lat": float("nan"), "lng": -46},
                  {"lat": -23.5, "lng": 500}):
        assert valid_position(wrong) is None


def test_click_events_do_not_return_zoom_or_camera_to_streamlit():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "mapa_eleicoes" /
           "interactive_map.py").read_text(encoding="utf-8")
    assert "on_change=on_map_change," in src
    assert '"last_clicked", "last_object_clicked", "last_object_clicked_count"' in src
    assert "return_on_hover=False" in src
    assert "st.rerun()" in src
    assert '"zoom", "center"' not in src


def test_main_map_restores_city_only_when_filter_scope_matches():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app.py").read_text(
        encoding="utf-8"
    )
    assert 'st.session_state.get("atlas_explorer_scope") == current_scope' in src
    assert "municipal_focus_bounds(geometry, selected_city) or full_bounds" in src
    assert "home_bounds=full_bounds" in src
    assert "map_view.fit_bounds(initial_bounds)" in src


def test_clicked_city_bounds_use_exact_ibge_polygon_not_nearest_neighbor():
    from mapa_eleicoes.map_navigation import municipal_focus_bounds

    shapes = geometry()
    assert municipal_focus_bounds(shapes, "3550308") == [
        [-24.0, -47.0], [-23.0, -46.0]
    ]
    assert municipal_focus_bounds(shapes, "3304557") == [
        [-23.0, -44.0], [-22.0, -43.0]
    ]
    assert municipal_focus_bounds(shapes, "0000000") is None
    assert municipal_focus_bounds(shapes, None) is None
    assert municipal_focus_bounds(shapes.drop(columns=["map_id"]), "3550308") is None


def test_map_click_coordinate_takes_priority_over_stale_feature_click():
    from unittest.mock import patch
    from mapa_eleicoes import interactive_map

    city = geometry()
    with patch.object(interactive_map.st, "session_state", {}):
        interactive_map._handle_click(
            {
                "last_clicked": {"lat": -23.5, "lng": -46.5},
                "last_object_clicked": {"lat": -22.5, "lng": -43.5},
                "last_object_clicked_count": 1,
            },
            city, None, zona="Todas", current_city=None,
        )
        assert interactive_map.st.session_state["atlas_explorer_focus"] == {
            "city": "3550308"
        }


def test_new_polygon_click_does_not_reuse_stale_last_clicked():
    from unittest.mock import patch
    from mapa_eleicoes import interactive_map

    old_click = (-23.5, -46.5)
    with patch.object(interactive_map.st, "session_state", {
        "atlas_explorer_last_click": {
            "map": old_click, "object": old_click, "object_count": 1,
        },
        "atlas_explorer_focus": {"city": "3550308"},
    }):
        interactive_map._handle_click(
            {
                "last_clicked": {"lat": old_click[0], "lng": old_click[1]},
                "last_object_clicked": {"lat": -22.5, "lng": -43.5},
                "last_object_clicked_count": 2,
            },
            geometry(), None, zona="Todas", current_city="3550308",
        )
        assert interactive_map.st.session_state["atlas_explorer_focus"] == {
            "city": "3304557"
        }


def test_duplicate_frontend_state_does_not_reset_focus():
    from unittest.mock import patch
    from mapa_eleicoes import interactive_map

    previous = {
        "map": (-23.5, -46.5),
        "object": (-23.5, -46.5),
        "object_count": 4,
    }
    with patch.object(interactive_map.st, "session_state", {
        "atlas_explorer_last_click": previous.copy(),
        "atlas_explorer_focus": {"city": "3550308"},
    }):
        interactive_map._handle_click(
            {
                "last_clicked": {"lat": -23.5, "lng": -46.5},
                "last_object_clicked": {"lat": -23.5, "lng": -46.5},
                "last_object_clicked_count": 4,
            },
            geometry(), None, zona="Todas", current_city=None,
        )
        assert interactive_map.st.session_state["atlas_explorer_last_click"] == previous
        assert interactive_map.st.session_state["atlas_explorer_focus"] == {
            "city": "3550308"
        }


def test_main_page_has_one_automatic_map_no_geographical_detail_panel():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    assert 'level = "Automático"' in src
    assert 'effective_level = "Município"' in src
    assert 'st.radio("Detalhamento geográfico"' not in src
    assert 'st.selectbox("Município"' in src
    assert 'st.selectbox("Zona"' in src
    assert 'CityFocus(' in src


def test_zone_overlay_follows_the_focused_city_not_first_900_state_zones():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "mapa_eleicoes" /
           "interactive_map.py").read_text(encoding="utf-8")
    assert 'wanted = {city} if city else (cities if uf != "Todas" else set())' in src
    assert 'base_map.add_child(group)' in src
    assert 'base_map.add_child(ZoomPanes(explorer_gates("Automático")))' in src
    assert 'gate_detail =' not in src
    assert 'feature_group_to_add=dynamic or None' in src
    # Camadas zonais não entram em dynamic; usado somente para locais.
    assert 'dynamic.append(group)' not in src.split('def _site_layer(', 1)[0]
