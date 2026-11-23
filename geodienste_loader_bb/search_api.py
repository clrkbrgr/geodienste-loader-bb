# -*- coding: utf-8 -*-
# Geodienste-Loader BB - QGIS-Plugin
# Copyright (C) 2026 Landesvermessung und Geobasisinformation Brandenburg
# SPDX-License-Identifier: GPL-3.0-or-later
"""Search API der LGB: Suche im ganzen Katalog und Ersatzbetrieb."""

from urllib.parse import urlencode

from .network import fetch_json
from .providers import split_legal_form

API_BASE = "https://search.geobasis-bb.de/v2"
BASE_URL = f"{API_BASE}/search"
COMPLETION_URL = f"{BASE_URL}/completion"

SOURCE_URL = BASE_URL
PROVIDERS_FILENAME = "providers_search_api.json"

# "query" ist Pflicht, "*" findet nichts.
SERVICE_TYPES = ("WMS", "WFS", "WMTS", "WCS",
                 "OAF", "OAT", "ATOM", "CSW", "REST", "UNKNOWN")

FLAG_FIELDS = {
    "opendata": "opendata",
    "inspire": "inspireIdentified",
    "nationwide": "nationwide",
}

_BASE_FILTERS = {
    "category": "metadata",
    "type": "service",
}

FIELD_SERVICE_TYPE = "serviceType"

# Ohne ".keyword" findet der Filter nichts.
FIELD_PROVIDER = "source.keyword"

PAGE_SIZE = 50


def build_search_url(query, filters=None, start=0, limit=PAGE_SIZE,
                     alphabetical=False):
    """Abfrage-URL. limit 0 liefert nur Zahlen."""
    params = [("query", query), ("start", start), ("limit", limit)]

    if alphabetical:
        params.append(("sortBy", "alphabetical"))
        params.append(("sortOrder", "asc"))

    all_filters = dict(_BASE_FILTERS)
    if filters:
        all_filters.update(filters)

    # Falsche Filternamen liefern null Treffer statt Fehler.
    for name, value in all_filters.items():
        params.append((f"filter[{name}]", value))

    return f"{BASE_URL}?{urlencode(params)}"


def parse_response(payload):
    """Antwort als Dict mit "total", "services" und "facets"."""
    if "results" not in payload or "total" not in payload:
        raise ValueError(
            "Unerwartete Antwort der Search API: "
            "Felder 'results' oder 'total' fehlen."
        )

    services = []
    for entry in payload["results"]:
        details = entry.get("categoryResult") or {}
        services.append({
            "id": entry.get("id", ""),
            "title": entry.get("title", ""),
            "description": details.get("description", ""),
            "service_type": details.get("serviceType", ""),
            "service_url": details.get("serviceUrl", ""),
            "metadata_url": details.get("metadataUrl", ""),
            "provider": details.get("source", ""),
            "classification": details.get("sourceClassification", ""),
            "flags": [
                flag for flag, field in FLAG_FIELDS.items()
                if details.get(field)
            ],
            "geometry": entry.get("geometry", ""),
        })

    facets = {}
    for stat in payload.get("stats", []):
        attribute = stat.get("attribute")
        if not attribute:
            continue
        facets[attribute] = [
            (value.get("value", ""), value.get("count", 0))
            for value in stat.get("vals", [])
        ]

    return {
        "total": payload["total"],
        "services": services,
        "facets": facets,
    }


def type_counts(facets):
    """Anzahl je Diensteart aus der Facette."""
    found = dict(facets.get(FIELD_SERVICE_TYPE, []))
    return {
        service_type: int(found.get(service_type, 0))
        for service_type in SERVICE_TYPES
    }


def flag_counts(facets):
    """Anzahl je Kennzeichnung, nur eine Obergrenze."""
    counts = {}
    for flag, field in FLAG_FIELDS.items():
        # Werte kommen als Text.
        values = {str(value).lower(): count
                  for value, count in facets.get(field, [])}
        counts[flag] = int(values.get("true", 0))
    return counts


def _build_filters(service_types=None, flags=None, provider=None):
    """Filter für eine Abfrage."""
    filters = {}

    if provider:
        filters[FIELD_PROVIDER] = provider

    if service_types:
        filters[FIELD_SERVICE_TYPE] = "|".join(service_types)

    for flag in (flags or ()):
        field = FLAG_FIELDS.get(flag)
        if field:
            filters[field] = "true"

    return filters


def search_services(query, service_types=None, flags=None, start=0,
                    limit=PAGE_SIZE):
    """Dienste zu einem Suchbegriff, nach Relevanz."""
    url = build_search_url(
        query,
        _build_filters(service_types, flags),
        start,
        limit,
    )
    return parse_response(fetch_json(url))


def search_services_by_type(service_type, flags=None, start=0,
                            limit=PAGE_SIZE, provider=None):
    """Dienste einer Art, alphabetisch."""
    url = build_search_url(
        service_type,
        _build_filters([service_type], flags, provider),
        start,
        limit,
        alphabetical=True,
    )
    return parse_response(fetch_json(url))


def fetch_completions(query, limit=8):
    """Titelvorschläge zur Eingabe."""
    params = [("query", query), ("limit", limit)]
    for name, value in _BASE_FILTERS.items():
        params.append((f"filter[{name}]", value))

    payload = fetch_json(f"{COMPLETION_URL}?{urlencode(params)}")

    titles = []
    for entry in payload.get("results", []):
        # "highlight" enthält HTML.
        value = (entry.get("value") or "").strip()
        if value and value not in titles:
            titles.append(value)
    return titles


# ----------------------------------------------------------------------
# Anbieter und ihre Dienste
# ----------------------------------------------------------------------


def provider_name_and_function(source, classification):
    """Name und Art eines Anbieters wie im Geoportal."""
    name, function = split_legal_form(source)
    if function:
        return name, function

    if classification == "Land":
        for word in ("Ministerium", "Landesamt"):
            if word in source:
                return source, word
        return source, "Landesbetrieb und Einrichtung des Landes"
    if classification == "Gemeindeverband":
        return source, "Verbandsgemeinde"
    if classification == "Landkreis, Kreis, Kreisfreie Stadt":
        return source, "Landkreis"
    if "Zweckverband" in source:
        return source, "Zweckverband"
    return source, "Sonstige"


def check_available():
    """Kurze Prüfung der Search API."""
    search_services_by_type(SERVICE_TYPES[0], limit=0)


def _all_of_type(service_type, provider=None, cancelled=None):
    """Alle Dienste einer Art, seitenweise."""
    start = 0
    while not (cancelled and cancelled()):
        result = search_services_by_type(
            service_type, start=start, provider=provider
        )
        page = result["services"]
        if not page:
            return
        yield page
        start += len(page)
        if start >= result["total"]:
            return


def fetch_services(provider_key, cancelled=None):
    """Alle Dienste eines Anbieters."""
    services = []
    seen = set()
    for service_type in SERVICE_TYPES:
        for page in _all_of_type(service_type, provider_key, cancelled):
            for service in page:
                # Gegen Doppelte bei verschobener Sortierung.
                if service["id"] not in seen:
                    seen.add(service["id"])
                    services.append(service)
    return services


def fetch_providers(cancelled=None, progress=None):
    """Zählt alle Anbieter über alle Dienste."""
    totals = {}
    for service_type in SERVICE_TYPES:
        if cancelled and cancelled():
            return None
        totals[service_type] = search_services_by_type(
            service_type, limit=0
        )["total"]
    grand_total = max(sum(totals.values()), 1)

    counts = {}
    classifications = {}
    seen = set()
    for service_type in SERVICE_TYPES:
        if not totals[service_type]:
            continue
        for page in _all_of_type(service_type, cancelled=cancelled):
            for service in page:
                if service["id"] in seen:
                    continue
                seen.add(service["id"])
                source = service["provider"].strip()
                counts[source] = counts.get(source, 0) + 1
                classifications.setdefault(source, service["classification"])
            if progress:
                progress(min(100.0 * len(seen) / grand_total, 100.0))
        if cancelled and cancelled():
            return None

    providers = []
    for source, count in counts.items():
        if not source:
            continue
        name, function = provider_name_and_function(
            source, classifications[source]
        )
        providers.append({
            "key": source,
            "name": name,
            "function": function,
            "service_count": count,
        })
    return providers
