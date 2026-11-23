# -*- coding: utf-8 -*-
# Geodienste-Loader BB - QGIS-Plugin
# Copyright (C) 2026 Landesvermessung und Geobasisinformation Brandenburg
# SPDX-License-Identifier: GPL-3.0-or-later
"""OGC API Tiles: Kachelvorlage und Zoomstufen."""

from .network import fetch_json

# Nur dieser Kachelsatz geht als XYZ-Quelle.
TILE_MATRIX_SET = "WebMercatorQuad"

# tileRow = y, tileCol = x
_TILE_PLACEHOLDERS = {
    "{tileMatrix}": "{z}",
    "{tileRow}": "{y}",
    "{tileCol}": "{x}",
}


def resolve_tile_source(service_url):
    """Kachelvorlage mit {z}/{x}/{y} und Zoomstufen eines Dienstes."""
    base = service_url.rstrip("/")
    tilesets = fetch_json(f"{base}/tiles?f=json").get("tilesets", [])

    tileset_url = None
    for tileset in tilesets:
        for link in tileset.get("links", []):
            href = link.get("href", "")
            if link.get("rel") == "self" and href.endswith(TILE_MATRIX_SET):
                tileset_url = href
                break

    if tileset_url is None:
        raise RuntimeError(
            f"Der Dienst bietet keinen Kachelsatz {TILE_MATRIX_SET}. "
            "Nur dieser lässt sich in QGIS als Kachelquelle einbinden."
        )

    details = fetch_json(f"{tileset_url}?f=json")

    template = ""
    for link in details.get("links", []):
        if link.get("rel") == "item":
            template = link.get("href", "")
            break

    if not template:
        raise RuntimeError("Der Kachelsatz nennt keine Kachel-URL.")

    for ogc_placeholder, qgis_placeholder in _TILE_PLACEHOLDERS.items():
        template = template.replace(ogc_placeholder, qgis_placeholder)

    limits = details.get("tileMatrixSetLimits", [])
    zoom_levels = [
        int(limit["tileMatrix"]) for limit in limits
        if str(limit.get("tileMatrix", "")).isdigit()
    ]
    zoom_min = min(zoom_levels) if zoom_levels else 0
    zoom_max = max(zoom_levels) if zoom_levels else 14

    return template, zoom_min, zoom_max
