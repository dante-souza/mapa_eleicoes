"""Folium basemap for the Atlas Eleitoral.

Uses public OpenStreetMap tiles without a CARTO API key. The dark styling is
applied only to raster tiles (not polygons/labels/tooltips), so our Dracula
palette is not distorted and the mandatory OSM attribution remains visible.
"""
from __future__ import annotations

import folium


DARK_TILE_CSS = """
<style>
/* Filter *only* the map raster layer: preserve geographic overlays. */
.leaflet-tile-pane .leaflet-tile {
    filter: invert(1) hue-rotate(180deg) saturate(.48) brightness(.78) contrast(1.12);
}
.leaflet-control-attribution {
    background: rgba(40, 42, 54, .94) !important;
    color: #f8f8f2 !important;
}
.leaflet-control-attribution a {
    color: #8be9fd !important;
}
</style>
"""


def atlas_map(location: list[float], *, dark: bool = True) -> folium.Map:
    """Build a working map without third-party API credentials."""
    result = folium.Map(
        location=location, zoom_start=5, tiles="OpenStreetMap",
        control_scale=True, prefer_canvas=True,
    )
    if dark:
        result.get_root().header.add_child(folium.Element(DARK_TILE_CSS))
    return result
