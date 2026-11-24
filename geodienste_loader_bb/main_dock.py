# -*- coding: utf-8 -*-
# Geodienste-Loader BB - QGIS-Plugin
# Copyright (C) 2026 Landesvermessung und Geobasisinformation Brandenburg
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bedienfeld mit den Reitern "Diensteanbieter" und "Dienste"."""

import os
import random
from datetime import datetime, timedelta, timezone

from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QLabel,
    QMessageBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from qgis.core import Qgis, QgsApplication, QgsMessageLog
from qgis.gui import QgsMessageBar

from . import edition, providers
from .catalog import Catalog
from .compat import enum_value
from .network import LOG_TAG
from .provider_manager_widget import ProviderManagerWidget
from .services_widget import ServicesWidget
from .tasks import ProviderListTask, SourceCheckTask
from .ui_helpers import plugin_icon


# Ersatzbetrieb: Abstand der Prüfungen.
RETRY_INTERVAL_MINUTES = 5

# Zuschlag gegen Gleichtakt vieler Rechner.
RETRY_JITTER_SECONDS = 60

BACK_ONLINE_MESSAGE_SECONDS = 10

# Rund 116 Anfragen, deshalb nicht bei jedem Start.
PROVIDER_LIST_MAX_AGE = timedelta(days=1)

# Rund 170 Anfragen an die Search API.
FALLBACK_LIST_MAX_AGE = timedelta(days=30)


class MainDock(QDockWidget):

    def __init__(self, parent=None, canvas=None):
        super().__init__("Geodienste-Loader BB", parent)
        self.setObjectName("GeodiensteLoaderDock")

        self._provider_task = None
        self._provider_task_quiet = False

        # Nie gleichzeitig mit _provider_task.
        self._check_task = None
        self._check_task_quiet = False

        self._fallback_list_task = None

        self._catalog = Catalog()

        self._retry_timer = QTimer(self)
        self._retry_timer.timeout.connect(self._check_preferred_source)

        try:
            provider_list = self._load_providers(self._catalog.current_source)
        except Exception as error:
            label = QLabel(
                self.tr(
                    "Die Liste der Diensteanbieter konnte nicht geladen "
                    "werden:\n"
                    "{error}\n\n"
                    "Die Datei {file} im Plugin-Verzeichnis fehlt oder "
                    "ist beschädigt. Plugin neu installieren."
                ).format(error=error, file=self._catalog.providers_filename())
            )
            label.setWordWrap(True)
            self.setWidget(label)
            return

        self.message_bar = QgsMessageBar(self)

        self.tabs = QTabWidget(self)
        self.tabs.setDocumentMode(True)

        self.provider_tab = ProviderManagerWidget(self)
        self.provider_tab.set_providers(
            provider_list.providers, provider_list.generated
        )
        self.tabs.addTab(
            self.provider_tab, plugin_icon(), self.tr("Diensteanbieter")
        )

        self.services_tab = ServicesWidget(self._catalog, canvas, self)
        self.tabs.addTab(self.services_tab, self.tr("Dienste"))

        container = QWidget(self)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        container_layout.addWidget(self.message_bar)
        container_layout.addWidget(self.tabs, 1)
        self.setWidget(container)

        self.provider_tab.provider_selected.connect(self._show_services)
        self.provider_tab.refresh_requested.connect(
            self._on_refresh_requested
        )
        self.services_tab.provider_total_known.connect(
            self.provider_tab.update_service_count
        )
        self.services_tab.provider_source_failed.connect(
            self._on_provider_source_failed
        )

        self._update_refresh_tooltip()

        # Nur bei veralteter gs-json-Liste neu holen.
        if (self._catalog.current_source == edition.GS_JSON
                and self._is_outdated(provider_list.generated)):
            self._refresh_provider_list(edition.GS_JSON)

        self._refresh_fallback_list_if_outdated()

    # ------------------------------------------------------------------
    # Anbieterliste
    # ------------------------------------------------------------------

    def _user_providers_path(self, source):
        return providers.user_path(
            QgsApplication.qgisSettingsDirPath(),
            self._catalog.providers_filename(source),
        )

    def _load_providers(self, source):
        """Lädt die jüngere von mitgelieferter Liste und Profil-Kopie."""
        bundled_path = os.path.join(
            os.path.dirname(__file__),
            self._catalog.providers_filename(source),
        )
        provider_list, warning = providers.load_newest(
            bundled_path, self._user_providers_path(source)
        )

        if warning:
            self._log(warning, "Warning")

        return provider_list

    def _on_refresh_requested(self):
        # Im Ersatzbetrieb nur prüfen.
        if self._catalog.is_fallback_active():
            self._start_source_check()
            return

        if self._catalog.current_source == edition.SEARCH_API:
            answer = QMessageBox.question(
                self,
                self.tr("Liste der Diensteanbieter aktualisieren"),
                self.tr(
                    "Die Search API liefert Diensteanbieter und "
                    "Dienstezahlen nur über die Dienste selbst. Dafür "
                    "werden alle rund 8000 Dienste gezählt: etwa 170 "
                    "Abfragen, Dauer etwa eine Minute. QGIS bleibt "
                    "währenddessen bedienbar.\n\n"
                    "Fortfahren?"
                ),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self._refresh_provider_list(self._catalog.current_source)

    def _refresh_provider_list(self, source, quiet=False):
        """Holt die Anbieterliste einer Quelle im Hintergrund."""
        if self._provider_task is not None or self._check_task is not None:
            return

        if quiet:
            busy_text = ""
        elif source == self._catalog.current_source:
            busy_text = self.tr(
                "Liste der Diensteanbieter wird aktualisiert ..."
            )
        else:
            busy_text = self.tr("Geoportal wird geprüft ...")
        self.provider_tab.set_busy(True, busy_text)

        task = ProviderListTask(self._catalog, source)
        self._provider_task = task
        self._provider_task_quiet = quiet

        # Gebundene Methoden: Qt trennt sie beim Löschen.
        task.taskCompleted.connect(self._on_providers_loaded)
        task.taskTerminated.connect(self._on_providers_failed)

        QgsApplication.taskManager().addTask(task)

    def _on_providers_loaded(self):
        """Zeigt und speichert die neue Liste."""
        task = self._provider_task
        if task is None or self.sender() is not task:
            return

        self._provider_task = None

        data = providers.build_provider_file(
            task.providers,
            providers.now_iso(),
            self._catalog.source_url(task.source),
        )

        message = ""
        try:
            providers.write_provider_file(
                self._user_providers_path(task.source), data
            )
        except OSError as error:
            message = self.tr(
                "Liste aktualisiert, konnte aber nicht gespeichert "
                "werden: {error}"
            ).format(error=error)
            self._log(message, "Warning")

        generated = providers.parse_generated(data["generated"])

        self._log(
            f"Liste der Diensteanbieter aktualisiert ({task.source}): "
            f"{data['provider_count']} Diensteanbieter, "
            f"{data['service_count']} Dienste.",
            "Info",
        )

        if task.source != self._catalog.current_source:
            self._return_to_preferred_source(task.providers, generated)
        else:
            self.provider_tab.set_providers(task.providers, generated)

        self.provider_tab.set_busy(False, message)

    def _on_providers_failed(self):
        """Fehler oder Abbruch beim Abruf der Liste."""
        task = self._provider_task
        if task is None or self.sender() is not task:
            return

        self._provider_task = None

        # Abbruch ist kein Ausfall.
        if not task.error_message:
            self.provider_tab.set_busy(
                False, self.tr("Aktualisierung abgebrochen.")
            )
            return

        can_fall_back = (
            task.source == self._catalog.preferred_source
            and self._catalog.fallback_source is not None
        )

        if can_fall_back and self._catalog.is_fallback_active():
            self._log(
                f"Geoportal weiterhin nicht erreichbar: {task.error_message}",
                "Info",
            )
            if self._provider_task_quiet:
                self.provider_tab.set_busy(False)
            else:
                self.provider_tab.set_busy(
                    False,
                    self.tr("Das Geoportal ist weiterhin nicht erreichbar."),
                )
            return

        if can_fall_back and self._activate_fallback(task.error_message):
            self.provider_tab.set_busy(False)
            return

        self.provider_tab.set_busy(
            False,
            self.tr("Aktualisierung fehlgeschlagen: {error}").format(
                error=task.error_message
            ),
        )

    def _refresh_fallback_list_if_outdated(self):
        """Holt eine veraltete Ersatzliste neu."""
        fallback = self._catalog.fallback_source
        if fallback is None:
            return

        # Nicht doppelt starten.
        if self._fallback_list_task is not None:
            return

        try:
            generated = self._load_providers(fallback).generated
        except (OSError, ValueError):
            generated = None

        if (generated is not None
                and datetime.now(timezone.utc) - generated
                <= FALLBACK_LIST_MAX_AGE):
            return

        task = ProviderListTask(self._catalog, fallback)
        self._fallback_list_task = task
        task.taskCompleted.connect(self._on_fallback_list_loaded)
        task.taskTerminated.connect(self._on_fallback_list_failed)
        QgsApplication.taskManager().addTask(task)

    def _on_fallback_list_loaded(self):
        """Speichert die neue Ersatzliste."""
        task = self._fallback_list_task
        if task is None or self.sender() is not task:
            return
        self._fallback_list_task = None

        data = providers.build_provider_file(
            task.providers,
            providers.now_iso(),
            self._catalog.source_url(task.source),
        )
        try:
            providers.write_provider_file(
                self._user_providers_path(task.source), data
            )
        except OSError as error:
            self._log(
                f"Liste für den Ersatzbetrieb geholt, aber nicht "
                f"gespeichert: {error}",
                "Warning",
            )
            return

        self._log(
            f"Liste für den Ersatzbetrieb aktualisiert ({task.source}): "
            f"{data['provider_count']} Diensteanbieter, "
            f"{data['service_count']} Dienste.",
            "Info",
        )

        if task.source == self._catalog.current_source:
            self.provider_tab.set_providers(
                task.providers, providers.parse_generated(data["generated"])
            )

    def _on_fallback_list_failed(self):
        task = self._fallback_list_task
        if task is None or self.sender() is not task:
            return
        self._fallback_list_task = None

        if task.error_message:
            self._log(
                f"Liste für den Ersatzbetrieb nicht aktualisiert: "
                f"{task.error_message}",
                "Info",
            )

    # ------------------------------------------------------------------
    # Ersatzbetrieb
    # ------------------------------------------------------------------

    def _on_provider_source_failed(self, source):
        """Abruf der Dienste gescheitert: Geoportal kurz prüfen."""
        if (source == self._catalog.preferred_source
                and self._catalog.fallback_source is not None
                and not self._catalog.is_fallback_active()):
            self._start_source_check(quiet=True)

    def _start_source_check(self, quiet=False):
        """Kurze Prüfung der bevorzugten Quelle."""
        if self._check_task is not None or self._provider_task is not None:
            return

        busy_text = "" if quiet else self.tr("Geoportal wird geprüft ...")
        self.provider_tab.set_busy(True, busy_text)

        task = SourceCheckTask(self._catalog, self._catalog.preferred_source)
        self._check_task = task
        self._check_task_quiet = quiet

        task.taskCompleted.connect(self._on_source_available)
        task.taskTerminated.connect(self._on_source_unavailable)

        QgsApplication.taskManager().addTask(task)

    def _on_source_available(self):
        """Die bevorzugte Quelle antwortet."""
        task = self._check_task
        if task is None or self.sender() is not task:
            return
        self._check_task = None
        quiet = self._check_task_quiet

        self.provider_tab.set_busy(False)

        if self._catalog.is_fallback_active():
            self._refresh_provider_list(task.source, quiet=quiet)
            return

        self._log(
            "Geoportal erreichbar, nur ein einzelner Abruf ist "
            "gescheitert. Kein Ersatzbetrieb.",
            "Info",
        )

    def _on_source_unavailable(self):
        """Prüfung gescheitert oder abgebrochen."""
        task = self._check_task
        if task is None or self.sender() is not task:
            return
        self._check_task = None
        quiet = self._check_task_quiet

        # Abbruch ist kein Ausfall.
        if not task.error_message:
            self.provider_tab.set_busy(False)
            return

        if self._catalog.is_fallback_active():
            self._log(
                f"Geoportal weiterhin nicht erreichbar: {task.error_message}",
                "Info",
            )
            if quiet:
                self.provider_tab.set_busy(False)
            else:
                self.provider_tab.set_busy(
                    False,
                    self.tr("Das Geoportal ist weiterhin nicht erreichbar."),
                )
            return

        self.provider_tab.set_busy(False)
        self._activate_fallback(task.error_message)

    def _activate_fallback(self, reason):
        """Schaltet auf die Ersatzquelle um."""
        fallback = self._catalog.fallback_source

        try:
            provider_list = self._load_providers(fallback)
        except (OSError, ValueError) as error:
            self._log(
                f"Geoportal nicht erreichbar ({reason}), aber die "
                f"Ersatzliste {self._catalog.providers_filename(fallback)} "
                f"ist nicht nutzbar: {error}",
                "Warning",
            )
            return False

        self._log(
            f"Geoportal nicht erreichbar, Ersatzbetrieb über die Search "
            f"API: {reason}",
            "Warning",
        )

        self._switch_source(
            fallback, provider_list.providers, provider_list.generated
        )

        self.message_bar.clearWidgets()
        self.message_bar.pushMessage(
            self.tr("Geoportal nicht erreichbar"),
            self.tr(
                "Die Diensteanbieter kommen vorübergehend aus der Search "
                "API (Stand der Liste: {date}). Das Plugin prüft alle "
                "{minutes} Minuten, ob das Geoportal wieder erreichbar ist."
            ).format(
                date=self._format_date(provider_list.generated),
                minutes=RETRY_INTERVAL_MINUTES,
            ),
            enum_value(Qgis, "MessageLevel", "Warning"),
            0,
        )

        self._retry_timer.setInterval(self._next_retry_interval_ms())
        self._retry_timer.start()
        return True

    @staticmethod
    def _next_retry_interval_ms():
        """Abstand bis zur nächsten Prüfung in ms."""
        # Zufall nur zur Lastverteilung, nicht für Sicherheit.
        jitter = random.uniform(0, RETRY_JITTER_SECONDS)  # nosec B311
        seconds = RETRY_INTERVAL_MINUTES * 60 + jitter
        return int(seconds * 1000)

    def _check_preferred_source(self):
        """Zeitgeber: Geoportal erneut prüfen."""
        if not self._catalog.is_fallback_active():
            self._retry_timer.stop()
            return

        self._retry_timer.setInterval(self._next_retry_interval_ms())

        self._start_source_check(quiet=True)

    def _return_to_preferred_source(self, provider_items, generated):
        """Beendet den Ersatzbetrieb."""
        self._retry_timer.stop()

        self._switch_source(
            self._catalog.preferred_source, provider_items, generated
        )
        self._log("Geoportal wieder erreichbar, Ersatzbetrieb beendet.",
                  "Info")

        self.message_bar.clearWidgets()
        self.message_bar.pushMessage(
            self.tr("Geoportal wieder erreichbar"),
            self.tr("Die Diensteanbieter kommen wieder aus dem Geoportal."),
            enum_value(Qgis, "MessageLevel", "Success"),
            BACK_ONLINE_MESSAGE_SECONDS,
        )

    def _switch_source(self, source, provider_items, generated):
        """Setzt Quelle und Anbieterliste gemeinsam."""
        self._catalog.set_source(source)
        self.provider_tab.set_providers(provider_items, generated)
        self.services_tab.on_provider_source_changed()
        self._update_refresh_tooltip()

    def _update_refresh_tooltip(self):
        if self._catalog.is_fallback_active():
            text = self.tr("Erreichbarkeit des Geoportals prüfen")
        else:
            text = self.tr("Liste der Diensteanbieter aktualisieren")
        self.provider_tab.set_refresh_tooltip(text)

    # ------------------------------------------------------------------
    # Hilfen
    # ------------------------------------------------------------------

    @staticmethod
    def _is_outdated(generated):
        """True, wenn eine Liste veraltet ist."""
        if generated is None:
            return True
        return datetime.now(timezone.utc) - generated > PROVIDER_LIST_MAX_AGE

    def _format_date(self, stamp):
        """Stand als TT.MM.JJJJ."""
        if stamp is None:
            return self.tr("unbekannt")
        return stamp.astimezone().strftime("%d.%m.%Y")

    @staticmethod
    def _log(message, level_name):
        QgsMessageLog.logMessage(
            message, LOG_TAG, enum_value(Qgis, "MessageLevel", level_name)
        )

    # ------------------------------------------------------------------
    # Aufräumen
    # ------------------------------------------------------------------

    def cleanup(self):
        """Bricht laufende Abfragen ab."""
        self._retry_timer.stop()

        if self._provider_task is not None:
            self._provider_task.cancel()
            self._provider_task = None

        if self._check_task is not None:
            self._check_task.cancel()
            self._check_task = None

        if self._fallback_list_task is not None:
            self._fallback_list_task.cancel()
            self._fallback_list_task = None

        for attribute in ("provider_tab", "services_tab"):
            tab = getattr(self, attribute, None)
            if tab is not None:
                tab.cleanup()

    # ------------------------------------------------------------------
    # Reiterwechsel
    # ------------------------------------------------------------------

    def _show_services(self, provider_key, provider_name):
        self.services_tab.show_provider(provider_key, provider_name)
        self.tabs.setCurrentWidget(self.services_tab)
