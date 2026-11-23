# -*- coding: utf-8 -*-
# Geodienste-Loader BB - QGIS-Plugin
# Copyright (C) 2026 Landesvermessung und Geobasisinformation Brandenburg
# SPDX-License-Identifier: GPL-3.0-or-later
"""Anbieter und Dienste über gs-json des Geoportals."""

from urllib.parse import quote

from .network import post_json

GS_JSON_URL = "https://geoportal.brandenburg.de/gs-json"
REGISTRY_URL = f"{GS_JSON_URL}/registry"
SEARCH_URL = f"{GS_JSON_URL}/search"

SOURCE_URL = GS_JSON_URL
PROVIDERS_FILENAME = "providers.json"

DETAIL_PAGE_URL = (
    "https://geoportal.brandenburg.de/detailansichtdienst/render"
    "?view=gdibb&url=https%3A%2F%2Fgeoportal.brandenburg.de"
    "%2Fgs-json%2Fxml%3Ffileid%3D"
)

MAX_RESULTS = 1000

FLAG_FIELDS = {
    "opendata": "opendata",
    "inspire": "inspire_identified",
    "nationwide": "nationwide",
}


def fetch_providers(cancelled=None, progress=None):
    """
    Alle Anbieter mit Art und Dienstezahl.

    Nicht monitoring verwenden, es zählt nur überwachte Dienste.
    """
    registry = _results(
        post_json(REGISTRY_URL, {"type": "service"}), "registry"
    )

    providers = []
    total = max(len(registry), 1)
    for index, (key, entry) in enumerate(registry.items()):
        if cancelled and cancelled():
            return None

        providers.append({
            "key": key,
            "name": (entry.get("name") or key).strip(),
            "function": (entry.get("function") or "").strip(),
            "service_count": count_services(key),
        })

        if progress:
            progress(100.0 * (index + 1) / total)

    return providers


def check_available():
    """Kurze Prüfung mit zwei Anfragen."""
    registry = _results(
        post_json(REGISTRY_URL, {"type": "service"}), "registry"
    )
    if not registry:
        raise RuntimeError(
            "Unerwartete Antwort von gs-json (registry): keine "
            "Diensteanbieter."
        )

    first_key = next(iter(registry))
    count_services(first_key)


def count_services(provider_key):
    """Anzahl der Dienste eines Anbieters."""
    payload = post_json(SEARCH_URL, {
        "query": {"datatype": "service", "provider": provider_key},
        "maxresults": 1,
    })
    matched = payload.get("matched") if isinstance(payload, dict) else None
    try:
        return int(matched)
    except (TypeError, ValueError):
        raise RuntimeError(
            "Unerwartete Antwort von gs-json (search): Feld 'matched' "
            f"fehlt oder ist keine Zahl ({provider_key})."
        )


def fetch_services(provider_key, cancelled=None):
    """Alle Dienste eines Anbieters."""
    payload = post_json(SEARCH_URL, {
        "query": {"datatype": "service", "provider": provider_key},
        "maxresults": MAX_RESULTS,
    })
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        raise RuntimeError(
            "Unerwartete Antwort von gs-json (search): "
            "Feld 'results' fehlt."
        )
    return [_service(entry) for entry in results]


def _detail_page_url(fileid):
    """Adresse der Detailansicht. Die fileid wird doppelt kodiert."""
    if not fileid:
        return ""
    inner = quote(fileid, safe="")
    return DETAIL_PAGE_URL + quote(inner, safe="")


def _service(entry):
    service = entry.get("service") or {}
    fileid = entry.get("fileid", "")
    return {
        "id": fileid,
        "title": entry.get("title", ""),
        "description": entry.get("abstract", ""),
        "service_type": (service.get("type") or "").upper(),
        "service_url": (service.get("url_capabilities")
                        or service.get("url", "")),
        "metadata_url": _detail_page_url(fileid),
        "provider": entry.get("organisationname", ""),
        "flags": [
            flag for flag, field in FLAG_FIELDS.items() if entry.get(field)
        ],
        "geometry": entry.get("bbox", ""),
    }


def _results(payload, name):
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, dict):
        raise RuntimeError(
            f"Unerwartete Antwort von gs-json ({name}): "
            "Feld 'results' fehlt."
        )
    return results
