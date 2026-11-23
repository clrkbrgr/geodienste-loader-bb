# -*- coding: utf-8 -*-
# Geodienste-Loader BB - QGIS-Plugin
# Copyright (C) 2026 Landesvermessung und Geobasisinformation Brandenburg
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bevorzugte Quelle und Ersatzquelle."""

GS_JSON = "gs-json"
SEARCH_API = "search-api"

PROVIDER_SOURCE = GS_JSON

_FALLBACKS = {
    GS_JSON: SEARCH_API,
    SEARCH_API: None,
}

FALLBACK_SOURCE = _FALLBACKS[PROVIDER_SOURCE]
