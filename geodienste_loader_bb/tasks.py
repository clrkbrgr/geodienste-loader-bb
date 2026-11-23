# -*- coding: utf-8 -*-
# Geodienste-Loader BB - QGIS-Plugin
# Copyright (C) 2026 Landesvermessung und Geobasisinformation Brandenburg
# SPDX-License-Identifier: GPL-3.0-or-later
"""Hintergrundaufgaben. In run() nichts an der Oberfläche anfassen."""

from qgis.PyQt.QtCore import QCoreApplication, pyqtSignal
from qgis.core import QgsTask

from . import ogc_tiles
from .catalog import FlagCount, ServicePage, TypeCount
from .compat import enum_value


def _can_cancel():
    return enum_value(QgsTask, "Flag", "CanCancel")


class ServiceSearchTask(QgsTask):
    """Holt Dienste seitenweise."""

    # (Dienste, Gesamtzahl)
    page_loaded = pyqtSignal(list, int)

    # (Diensteart, Anzahl)
    type_total = pyqtSignal(str, int)

    # (Kennzeichnung, Anzahl)
    flag_total = pyqtSignal(str, int)

    def __init__(self, catalog, query="", provider=None, service_types=None,
                 flags=None, start=0, limit=None, refresh=False):
        super().__init__(
            QCoreApplication.translate(
                "GeodiensteLoaderBB",
                "Geodienste-Loader BB: Dienste suchen",
            ),
            _can_cancel(),
        )
        self._catalog = catalog
        self._query = query
        self.provider = provider
        # Quelle beim Start festhalten.
        self.source = catalog.current_source
        self._service_types = list(service_types or ())
        self._flags = set(flags or ())
        self._start = start
        self._limit = limit
        self._refresh = refresh

        self.reports_type_totals = catalog.reports_type_counts(
            query, self._service_types, self._flags, provider
        )
        self.reports_flag_totals = catalog.reports_flag_counts(
            query, provider
        )
        self.reports_provider_total = catalog.reports_provider_total(
            query, self._service_types, self._flags, provider
        )

        self.error_message = ""
        self.error_detail = ""
        self.loaded_count = 0
        self.total = 0
        self.truncated = False

    def run(self):
        try:
            pages = self._catalog.list_services(
                query=self._query,
                provider=self.provider,
                service_types=self._service_types,
                flags=self._flags,
                start=self._start,
                limit=self._limit,
                refresh=self._refresh,
                cancelled=self.isCanceled,
                source=self.source,
            )

            for item in pages:
                if self.isCanceled():
                    return False

                if isinstance(item, TypeCount):
                    self.type_total.emit(item.service_type, item.count)
                    continue

                if isinstance(item, FlagCount):
                    self.flag_total.emit(item.flag, item.count)
                    continue

                if not isinstance(item, ServicePage):
                    continue

                self.total = max(self.total, item.total)
                self.loaded_count += len(item.services)

                # Auch leere Seiten tragen die Gesamtzahl.
                self.page_loaded.emit(item.services, self.total)
                self._report_progress()

        except Exception as error:
            self.error_message = str(error)
            self.error_detail = getattr(error, "detail", "")
            return False

        self.truncated = self.loaded_count < self.total - self._start
        return not self.isCanceled()

    def _report_progress(self):
        reference = max(self.total - self._start, 1)
        self.setProgress(min(100.0 * self.loaded_count / reference, 100.0))


class ProviderListTask(QgsTask):
    """Holt die Anbieterliste."""

    def __init__(self, catalog, source):
        super().__init__(
            QCoreApplication.translate(
                "GeodiensteLoaderBB",
                "Geodienste-Loader BB: Liste der Diensteanbieter "
                "aktualisieren",
            ),
            _can_cancel(),
        )
        self._catalog = catalog
        self.source = source
        self.providers = []
        self.error_message = ""

    def run(self):
        try:
            providers = self._catalog.list_providers(
                source=self.source,
                cancelled=self.isCanceled,
                progress=self.setProgress,
            )
        except Exception as error:
            self.error_message = str(error)
            return False

        if self.isCanceled() or providers is None:
            return False

        self.providers = providers
        return True


class SourceCheckTask(QgsTask):
    """Kurze Prüfung einer Quelle."""

    def __init__(self, catalog, source):
        super().__init__(
            QCoreApplication.translate(
                "GeodiensteLoaderBB",
                "Geodienste-Loader BB: Geoportal prüfen",
            ),
            _can_cancel(),
        )
        self._catalog = catalog
        self.source = source
        self.error_message = ""

    def run(self):
        try:
            self._catalog.check_source(self.source)
        except Exception as error:
            self.error_message = str(error)
            return False
        return not self.isCanceled()


class VectorTileInfoTask(QgsTask):
    """Ermittelt Kachelvorlage und Zoomstufen."""

    def __init__(self, service_url, layer_name):
        super().__init__(
            QCoreApplication.translate(
                "GeodiensteLoaderBB",
                "Geodienste-Loader BB: Kachelsatz ermitteln",
            ),
            _can_cancel(),
        )
        self.service_url = service_url
        self.layer_name = layer_name
        self.template = ""
        self.zoom_min = 0
        self.zoom_max = 0
        self.error_message = ""

    def run(self):
        try:
            self.template, self.zoom_min, self.zoom_max = \
                ogc_tiles.resolve_tile_source(self.service_url)
        except Exception as error:
            self.error_message = str(error)
            return False
        return not self.isCanceled()


class CompletionTask(QgsTask):
    """Holt Vorschläge zur Eingabe."""

    # (Vorschläge, Eingabe)
    completions_ready = pyqtSignal(list, str)

    def __init__(self, catalog, query, provider=None):
        super().__init__(
            QCoreApplication.translate(
                "GeodiensteLoaderBB",
                "Geodienste-Loader BB: Vorschläge",
            ),
            _can_cancel(),
        )
        self._catalog = catalog
        self._query = query
        self._provider = provider
        self.error_message = ""

    def run(self):
        try:
            titles = self._catalog.completions(
                self._query, provider=self._provider
            )
        except Exception as error:
            self.error_message = str(error)
            return False

        if self.isCanceled():
            return False

        self.completions_ready.emit(titles, self._query)
        return True
