# -*- coding: utf-8 -*-
# Geodienste-Loader BB - QGIS-Plugin
# Copyright (C) 2026 Landesvermessung und Geobasisinformation Brandenburg
# SPDX-License-Identifier: GPL-3.0-or-later
"""Katalog: Anbieter und Dienste aus der aktuellen Quelle."""

from . import edition, gs_json, search_api
from .providers import (
    filter_services,
    make_provider,
    services_from_api,
    sort_providers,
)

SERVICE_TYPES = search_api.SERVICE_TYPES
FLAGS = tuple(search_api.FLAG_FIELDS)

PAGE_SIZE = search_api.PAGE_SIZE


class ServicePage:
    """Eine Seite Dienste mit bisheriger Gesamtzahl."""

    def __init__(self, services, total):
        self.services = services
        self.total = total


class TypeCount:
    """Anzahl der Dienste einer Diensteart."""

    def __init__(self, service_type, count):
        self.service_type = service_type
        self.count = count


class FlagCount:
    """Anzahl der Dienste mit einer Kennzeichnung."""

    def __init__(self, flag, count):
        self.flag = flag
        self.count = count


def _with_known_types(raw_services):
    """Unbekannte Arten zählen als UNKNOWN."""
    for raw in raw_services:
        if raw.get("service_type") not in SERVICE_TYPES:
            raw["service_type"] = "UNKNOWN"
    return raw_services


def source_module(source):
    """Modul der Quelle."""
    if source == edition.GS_JSON:
        return gs_json
    if source == edition.SEARCH_API:
        return search_api
    raise ValueError(f"Unbekannte Quelle: {source}")


class Catalog:
    """Anbieter und Dienste."""

    def __init__(self, page_size=PAGE_SIZE):
        self._page_size = page_size

        self._source = edition.PROVIDER_SOURCE

        # Kennungen sind je Quelle verschieden.
        self._provider_services = {}

    # ------------------------------------------------------------------
    # Quelle
    # ------------------------------------------------------------------

    @property
    def current_source(self):
        return self._source

    @property
    def preferred_source(self):
        return edition.PROVIDER_SOURCE

    @property
    def fallback_source(self):
        return edition.FALLBACK_SOURCE

    def is_fallback_active(self):
        return self._source != self.preferred_source

    def set_source(self, source):
        """Schaltet die Quelle um. Laufende Tasks behalten ihre."""
        source_module(source)
        self._source = source

    # ------------------------------------------------------------------
    # Anbieter
    # ------------------------------------------------------------------

    def list_providers(self, source=None, cancelled=None, progress=None):
        """Alle Anbieter einer Quelle, None bei Abbruch."""
        module = source_module(source or self._source)
        raw = module.fetch_providers(cancelled, progress)
        if raw is None:
            return None
        return sort_providers(
            make_provider(
                entry["key"], entry["name"], entry["function"],
                entry["service_count"],
            )
            for entry in raw
        )

    def check_source(self, source=None):
        """Kurze Prüfung einer Quelle."""
        source_module(source or self._source).check_available()

    def source_url(self, source=None):
        return source_module(source or self._source).SOURCE_URL

    def providers_filename(self, source=None):
        return source_module(source or self._source).PROVIDERS_FILENAME

    # ------------------------------------------------------------------
    # Dienste
    # ------------------------------------------------------------------

    def reports_type_counts(self, query, service_types, flags, provider):
        """True, wenn ein Lauf alle Dienstearten zählt."""
        if provider:
            return True
        if query.strip():
            return not flags
        return not service_types

    def reports_flag_counts(self, query, provider):
        """True, wenn ein Lauf Zahlen je Kennzeichnung meldet."""
        return bool(provider) or bool(query.strip())

    def reports_provider_total(self, query, service_types, flags, provider):
        """
        True, wenn ein Lauf alle Dienste eines Anbieters ungefiltert zählt.
        """
        return (bool(provider) and not query.strip() and not service_types
                and not flags)

    def list_services(self, query="", provider=None, service_types=None,
                      flags=None, start=0, limit=None, refresh=False,
                      cancelled=None, source=None):
        """Dienste als Generator von TypeCount, FlagCount und ServicePage."""
        types = list(service_types or ())
        flags = set(flags or ())
        query = query.strip()

        if provider:
            yield from self._provider_listing(
                source or self._source,
                provider, query, types, flags, refresh, cancelled,
            )
            return

        limit = self._page_size if limit is None else limit
        if query:
            yield from self._search(query, types, flags, start, limit,
                                    cancelled)
        else:
            yield from self._list_by_type(types or list(SERVICE_TYPES),
                                          flags, start, limit, cancelled)

    def _provider_listing(self, source, provider, query, types, flags,
                          refresh, cancelled):
        """Dienste eines Anbieters, zwischengespeichert und lokal gefiltert."""
        cache_key = (source, provider)
        services = None if refresh else self._provider_services.get(cache_key)
        if services is None:
            raw = _with_known_types(
                source_module(source).fetch_services(provider, cancelled)
            )
            if cancelled and cancelled():
                return
            services = sorted(services_from_api(raw),
                              key=lambda service: service.title.casefold())
            self._provider_services[cache_key] = services

        # Ohne Typfilter, damit die übrigen Knöpfe bleiben.
        matching = filter_services(services, query, None, flags)
        for service_type in SERVICE_TYPES:
            yield TypeCount(
                service_type,
                sum(1 for service in matching if service.type == service_type),
            )

        for flag in FLAGS:
            yield FlagCount(
                flag,
                len(filter_services(services, query, types, flags | {flag})),
            )

        shown = filter_services(matching, service_types=types)
        yield ServicePage(shown, len(shown))

    def _search(self, query, types, flags, start, limit, cancelled):
        """Treffer nach Relevanz."""
        position = start
        loaded = 0

        while True:
            if cancelled and cancelled():
                return

            result = search_api.search_services(
                query, service_types=types, flags=flags, start=position,
                limit=min(search_api.PAGE_SIZE, limit - loaded),
            )
            if cancelled and cancelled():
                return

            if loaded == 0:
                if not flags:
                    counts = search_api.type_counts(result["facets"])
                    for service_type, count in counts.items():
                        yield TypeCount(service_type, count)
                for flag, count in search_api.flag_counts(
                        result["facets"]).items():
                    yield FlagCount(flag, count)

            total = result["total"]
            services = result["services"]
            if not services:
                return

            yield ServicePage(services_from_api(services), total)
            loaded += len(services)
            position += len(services)

            if position >= total or loaded >= limit:
                return

    def _list_by_type(self, types, flags, start, limit, cancelled):
        """Auflistung ohne Suchbegriff, Art für Art."""
        skip = start
        loaded = 0
        total = 0

        for index, service_type in enumerate(types):
            if loaded >= limit:
                yield from self._remaining_totals(
                    types[index:], flags, total, start, cancelled
                )
                return

            if cancelled and cancelled():
                return

            result = search_api.search_services_by_type(
                service_type, flags=flags, start=skip,
            )
            if cancelled and cancelled():
                return

            type_total = result["total"]
            total += type_total
            # Null melden, dann verschwindet der Knopf.
            yield TypeCount(service_type, type_total)

            if skip >= type_total:
                skip -= type_total
                continue

            position = skip
            skip = 0

            while True:
                services = result["services"][:max(limit - loaded, 0)]
                if not services:
                    break

                yield ServicePage(services_from_api(services), total)
                loaded += len(services)
                position += len(services)

                if position >= type_total:
                    break
                if loaded >= limit:
                    yield from self._remaining_totals(
                        types[index + 1:], flags, total, start, cancelled
                    )
                    return

                if cancelled and cancelled():
                    return
                result = search_api.search_services_by_type(
                    service_type, flags=flags, start=position,
                )
                if cancelled and cancelled():
                    return

    def _remaining_totals(self, remaining_types, flags, total, start,
                          cancelled):
        """Zahlen der übrigen Arten und Gesamtzahl."""
        if start > 0:
            return

        for service_type in remaining_types:
            if cancelled and cancelled():
                return
            result = search_api.search_services_by_type(
                service_type, flags=flags, limit=0,
            )
            total += result["total"]
            yield TypeCount(service_type, result["total"])

        yield ServicePage([], total)

    # ------------------------------------------------------------------
    # Vorschläge
    # ------------------------------------------------------------------

    def completions(self, query, provider=None, limit=8):
        """Titelvorschläge zur Eingabe."""
        if provider:
            titles = []
            cached = self._provider_services.get((self._source, provider), [])
            for service in filter_services(cached, query):
                if service.title not in titles:
                    titles.append(service.title)
                if len(titles) >= limit:
                    break
            return titles
        return search_api.fetch_completions(query, limit=limit)
