# -*- coding: utf-8 -*-
# Geodienste-Loader BB - QGIS-Plugin
# Copyright (C) 2026 Landesvermessung und Geobasisinformation Brandenburg
# SPDX-License-Identifier: GPL-3.0-or-later
"""Reiter "Dienste"."""

import html

from qgis.PyQt.QtCore import (
    QCoreApplication,
    QStringListModel,
    QUrl,
    Qt,
    QTimer,
    pyqtSignal,
)
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCompleter,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsApplication
from qgis.gui import QgsFilterLineEdit

from . import layer_loader, map_extent
from .catalog import FLAGS, SERVICE_TYPES
from .tasks import CompletionTask, ServiceSearchTask, VectorTileInfoTask
from .ui_helpers import (
    FlowWidget,
    apply_layout_style,
    make_filter_button,
    make_icon_button,
    make_separator,
    plain_text_tooltip,
    save_table_state,
    setup_table_header,
    theme_icon,
)

SEARCH_DELAY_MS = 350

MIN_COMPLETION_CHARS = 3

COLUMNS_SETTINGS_KEY = "geodienste_loader_bb/dienste/spalten"


def flag_label(key):
    """Beschriftung einer Kennzeichnung."""
    labels = {
        "opendata": "Open Data",
        "inspire": "INSPIRE",
        "nationwide": QCoreApplication.translate(
            "GeodiensteLoaderBB", "Landesweit"
        ),
    }
    return labels[key]


def type_label(service_type):
    """Beschriftung einer Diensteart."""
    if service_type == "UNKNOWN":
        return QCoreApplication.translate("GeodiensteLoaderBB", "Unbekannt")
    return service_type


class ServicesWidget(QWidget):

    provider_total_known = pyqtSignal(str, int)

    provider_source_failed = pyqtSignal(str)

    def __init__(self, catalog, canvas=None, parent=None):
        super().__init__(parent)

        self._catalog = catalog
        self._canvas = canvas
        self._provider = None
        self._services = []
        self._total = 0
        self._task = None

        self._type_counts = {}
        self._counted_for = None

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DELAY_MS)

        self._completion_timer = QTimer(self)
        self._completion_timer.setSingleShot(True)
        self._completion_timer.setInterval(180)

        self._completion_task = None
        self._tile_task = None

        self._shown_once = False

        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # Aufbau
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = apply_layout_style(QVBoxLayout(self))

        header_layout = QHBoxLayout()
        header_layout.setSpacing(6)

        self.provider_label = QLabel()
        self.provider_label.setWordWrap(True)
        self.provider_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        header_layout.addWidget(self.provider_label, 1)

        self.all_button = QPushButton(self.tr("Gesamter Katalog"))
        self.all_button.setIcon(theme_icon("mActionZoomFullExtent.svg"))
        self.all_button.setToolTip(
            self.tr(
                "Zeigt alle Dienste des Katalogs. Diensteanbieter, "
                "Suchbegriff und Filter nach Diensteart werden "
                "zurückgesetzt."
            )
        )
        header_layout.addWidget(self.all_button)

        layout.addLayout(header_layout)

        self.text_edit = QgsFilterLineEdit()
        self.text_edit.setPlaceholderText(self.tr("Name des Dienstes"))
        self.text_edit.setShowSearchIcon(True)

        self._completion_model = QStringListModel(self)
        completer = QCompleter(self._completion_model, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        # Vorschläge nicht von Qt filtern lassen.
        completer.setCompletionMode(
            QCompleter.CompletionMode.UnfilteredPopupCompletion
        )
        completer.setMaxVisibleItems(10)
        self.text_edit.setCompleter(completer)
        self._completer = completer

        layout.addWidget(self.text_edit)

        self.filter_bar = FlowWidget()

        self.flag_buttons = {}
        for key in FLAGS:
            button = make_filter_button(flag_label(key))
            self.filter_bar.addWidget(button)
            self.flag_buttons[key] = button
            self._set_flag_available(key, True)

        self.filter_bar.addWidget(make_separator())

        self.type_buttons = {}
        for service_type in SERVICE_TYPES:
            button = make_filter_button(
                type_label(service_type),
                self.tr("Nur Dienste der Art {type}").format(
                    type=type_label(service_type)
                ),
            )
            self.filter_bar.addWidget(button)
            self.type_buttons[service_type] = button

        layout.addWidget(self.filter_bar)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [self.tr("Titel"), self.tr("Typ"), self.tr("Diensteanbieter")]
        )
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(False)
        self.table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )

        header = setup_table_header(
            self.table, [None, 60, 130], COLUMNS_SETTINGS_KEY
        )
        header.setHighlightSections(False)
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        # restoreState() holt eine ausgeblendete Spalte zurück.
        self._set_provider_column_visible(True)

        layout.addWidget(self.table)

        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(6)

        self.more_button = QPushButton(self.tr("Weitere laden"))
        self.more_button.setIcon(theme_icon("mActionAdd.svg"))
        self.more_button.setVisible(False)
        footer_layout.addWidget(self.more_button)
        footer_layout.addStretch(1)

        self.copy_button = make_icon_button(
            "mActionEditCopy.svg",
            self.tr("Dienst-URL in die Zwischenablage kopieren"),
            self.tr("URL"),
        )
        self.copy_button.setEnabled(False)
        footer_layout.addWidget(self.copy_button)

        self.metadata_button = make_icon_button(
            "propertyicons/metadata.svg",
            self.tr("Metadaten im Geoportal Brandenburg öffnen (Browser)"),
            self.tr("Metadaten"),
        )
        self.metadata_button.setEnabled(False)
        footer_layout.addWidget(self.metadata_button)

        self.zoom_button = make_icon_button(
            "mActionZoomToLayer.svg",
            self.tr("Karte auf die Ausdehnung des Dienstes zoomen"),
            self.tr("Zoom"),
        )
        self.zoom_button.setEnabled(False)
        footer_layout.addWidget(self.zoom_button)

        self.load_button = QPushButton(self.tr("Layer laden"))
        self.load_button.setIcon(theme_icon("mActionAddWmsLayer.svg"))
        self.load_button.setEnabled(False)
        footer_layout.addWidget(self.load_button)

        layout.addLayout(footer_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximumHeight(6)
        layout.addWidget(self.progress_bar)

        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        self.result_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(self.result_label)

        self._clear_provider_label()

    def _connect_signals(self):
        self.text_edit.textChanged.connect(self._search_timer.start)
        self.text_edit.textChanged.connect(self._completion_timer.start)
        self._search_timer.timeout.connect(self._start_new_search)
        self._completion_timer.timeout.connect(self._request_completions)
        self._completer.activated.connect(self._on_completion_chosen)
        for button in self.flag_buttons.values():
            button.toggled.connect(self._start_new_search)
        for button in self.type_buttons.values():
            button.toggled.connect(self._start_new_search)
        self.all_button.clicked.connect(self._clear_provider)

        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.itemDoubleClicked.connect(self._load_selected)
        self.table.customContextMenuRequested.connect(
            self._show_context_menu
        )
        self.load_button.clicked.connect(self._load_selected)
        self.copy_button.clicked.connect(self._copy_selected_url)
        self.metadata_button.clicked.connect(self._open_selected_metadata)
        self.zoom_button.clicked.connect(self._zoom_to_selected)
        self.more_button.clicked.connect(self._load_more)

    # ------------------------------------------------------------------
    # Öffentliche Methoden
    # ------------------------------------------------------------------

    def showEvent(self, event):
        """Lädt beim ersten Anzeigen den ganzen Katalog."""
        super().showEvent(event)
        if self._shown_once:
            return
        self._shown_once = True
        nothing_loaded = (self._provider is None and self._task is None
                          and not self._services)
        if nothing_loaded:
            self._start_new_search()

    def show_provider(self, provider_key, provider_name):
        """Zeigt die Dienste eines Anbieters."""
        self._provider = provider_key
        # Maskieren, "&" bricht sonst den Rich Text.
        self.provider_label.setText(
            self.tr("Diensteanbieter: <b>{name}</b>").format(
                name=html.escape(provider_name)
            )
        )
        self.provider_label.setToolTip(plain_text_tooltip(provider_name))
        self._set_provider_column_visible(False)
        self._clear_search_text()
        self._reset_type_buttons()
        self._enable_flag_buttons()
        self._clear_results()
        self._run_task(start=0, refresh=True)

    def on_provider_source_changed(self):
        """Quelle umgeschaltet: zurück zum ganzen Katalog."""
        if self._provider is not None:
            self._clear_provider()

    def _clear_search_text(self):
        """Leert das Suchfeld ohne neue Abfrage."""
        self._search_timer.stop()
        self._completion_timer.stop()
        self.text_edit.blockSignals(True)
        self.text_edit.clear()
        self.text_edit.blockSignals(False)
        self._completion_model.setStringList([])

    # ------------------------------------------------------------------
    # Filterzustand
    # ------------------------------------------------------------------

    def _active_types(self):
        """Eingeschaltete Dienstearten."""
        return [
            service_type
            for service_type, button in self.type_buttons.items()
            if button.isChecked()
        ]

    def _active_flags(self):
        return {
            key for key, button in self.flag_buttons.items()
            if button.isChecked()
        }

    def _count_context(self):
        return (self._provider, self.text_edit.text().strip(),
                frozenset(self._active_flags()))

    def _clear_provider_label(self):
        self.provider_label.setText(self.tr("Alle Diensteanbieter"))
        self.provider_label.setToolTip(
            self.tr(
                "Einen Diensteanbieter im Reiter \"Diensteanbieter\" "
                "wählen."
            )
        )

    def _clear_provider(self):
        """Zurück zum ganzen Katalog."""
        self._provider = None
        self._clear_provider_label()
        self._set_provider_column_visible(True)
        self._clear_search_text()
        self._reset_type_buttons()
        self._enable_flag_buttons()
        self._start_new_search()

    def _set_provider_column_visible(self, visible):
        # Kein Stretch, er löst ständig Signale aus.
        self.table.setColumnHidden(2, not visible)

    def _reset_type_buttons(self):
        """Versteckt alle Typknöpfe."""
        self._type_counts = {}
        self._counted_for = None
        for service_type, button in self.type_buttons.items():
            # Ohne blockSignals startet jeder Knopf eine Abfrage.
            button.blockSignals(True)
            button.setChecked(False)
            button.setText(type_label(service_type))
            button.setVisible(False)
            button.blockSignals(False)
        self.filter_bar.refresh()

    def _set_flag_available(self, flag, available):
        """Kennzeichnung wählbar oder ausgegraut."""
        button = self.flag_buttons[flag]
        button.setEnabled(available)
        label = flag_label(flag)
        if available:
            button.setToolTip(
                self.tr("Nur Dienste mit Kennzeichnung \"{label}\"").format(
                    label=label
                )
            )
        else:
            button.setToolTip(
                self.tr(
                    "Kein Dienst der aktuellen Auswahl hat die "
                    "Kennzeichnung \"{label}\""
                ).format(label=label)
            )

    def _enable_flag_buttons(self):
        for flag in self.flag_buttons:
            self._set_flag_available(flag, True)

    # ------------------------------------------------------------------
    # Abfragen
    # ------------------------------------------------------------------

    def _request_completions(self):
        text = self.text_edit.text().strip()
        if len(text) < MIN_COMPLETION_CHARS:
            self._completion_model.setStringList([])
            return

        if self._completion_task is not None:
            self._completion_task.cancel()

        task = CompletionTask(self._catalog, text, provider=self._provider)
        self._completion_task = task
        task.completions_ready.connect(self._on_completions_ready)
        QgsApplication.taskManager().addTask(task)

    def _on_completions_ready(self, titles, query):
        if self.sender() is not self._completion_task:
            return
        self._completion_task = None

        if query != self.text_edit.text().strip():
            return

        self._completion_model.setStringList(titles)

    def _on_completion_chosen(self, text):
        self._search_timer.stop()
        self._completion_timer.stop()
        self.text_edit.setText(text)
        self._start_new_search()

    def _start_new_search(self):
        self._clear_results()
        self._run_task(start=0)

    def _clear_results(self):
        self._services = []
        self._total = 0
        self.table.setRowCount(0)

    def _is_current_task(self):
        """True, wenn das Signal vom aktuellen Task kommt."""
        return self._task is not None and self.sender() is self._task

    def _load_more(self):
        self._run_task(start=len(self._services))

    def _run_task(self, start, refresh=False):
        if self._task is not None:
            self._task.cancel()

        self._set_busy(True)

        task = ServiceSearchTask(
            self._catalog,
            self.text_edit.text(),
            provider=self._provider,
            service_types=self._active_types(),
            flags=self._active_flags(),
            start=start,
            refresh=refresh,
        )
        # Referenz auf den laufenden Task halten.
        self._task = task

        # Gebundene Methoden: Qt trennt sie beim Löschen.
        task.page_loaded.connect(self._on_page_loaded)
        if task.reports_type_totals:
            self._counted_for = self._count_context()
            task.type_total.connect(self._on_type_total)
        else:
            self._show_uncounted_type_buttons()
        if task.reports_flag_totals:
            task.flag_total.connect(self._on_flag_total)
        else:
            self._enable_flag_buttons()
        task.taskCompleted.connect(self._on_task_done)
        task.taskTerminated.connect(self._on_task_failed)

        QgsApplication.taskManager().addTask(task)

    def _set_busy(self, busy):
        self.progress_bar.setVisible(busy)
        if busy:
            self.progress_bar.setRange(0, 0)
            self.more_button.setVisible(False)
            self.result_label.setText(self.tr("Suche läuft ..."))

    def _on_type_total(self, service_type, count):
        """Zahl an einem Typknopf."""
        if not self._is_current_task():
            return

        button = self.type_buttons.get(service_type)
        if button is None:
            return

        self._type_counts[service_type] = count
        button.setText(f"{type_label(service_type)} · {count}")
        button.setVisible(count > 0 or button.isChecked())
        self.filter_bar.refresh()

    def _on_flag_total(self, flag, count):
        """Graut eine Kennzeichnung ohne Treffer aus."""
        if not self._is_current_task():
            return

        button = self.flag_buttons.get(flag)
        if button is not None:
            self._set_flag_available(flag, count > 0 or button.isChecked())

    def _show_uncounted_type_buttons(self):
        """Typknöpfe für einen Lauf ohne Zahlen."""
        stale = self._counted_for != self._count_context()
        for service_type, button in self.type_buttons.items():
            if stale:
                button.setText(type_label(service_type))
                button.setVisible(True)
            elif service_type not in self._type_counts:
                button.setVisible(True)
        self.filter_bar.refresh()

    def _on_page_loaded(self, services, total):
        if not self._is_current_task():
            return

        self._total = max(self._total, total)

        first_row = len(self._services)
        self._services.extend(services)
        self._append_rows(first_row, services)
        self._update_result_label(finished=False)

    def _on_task_done(self):
        if not self._is_current_task():
            return

        task = self._task
        self._task = None
        self.progress_bar.setVisible(False)
        self._update_result_label(finished=True)

        if (task.reports_provider_total and self._provider
                and task.source == self._catalog.current_source):
            self.provider_total_known.emit(self._provider, self._total)

    def _on_task_failed(self):
        if not self._is_current_task():
            return

        task = self._task
        self._task = None
        self.progress_bar.setVisible(False)
        self._show_uncounted_type_buttons()
        self._enable_flag_buttons()
        if task.error_message:
            text = self.tr("Fehler: {error}").format(error=task.error_message)

            if not task.provider:
                text += " " + self.tr(
                    "Die Dienste eines Diensteanbieters lassen sich "
                    "weiterhin über den Reiter \"Diensteanbieter\" aufrufen."
                )
            self.result_label.setText(text)

            # Wörtlich, kann "<" oder "&" enthalten.
            self.result_label.setToolTip(
                plain_text_tooltip(task.error_detail or task.error_message)
            )

            if task.provider:
                self.provider_source_failed.emit(task.source)
        else:
            self.result_label.setText(self.tr("Abfrage abgebrochen."))

    def cleanup(self):
        """Bricht laufende Abfragen ab und sichert die Spaltenbreiten."""
        if self._task is not None:
            self._task.cancel()
            self._task = None

        if self._completion_task is not None:
            self._completion_task.cancel()
            self._completion_task = None

        if self._tile_task is not None:
            self._tile_task.cancel()
            self._tile_task = None

        save_table_state(self.table, COLUMNS_SETTINGS_KEY)

    # ------------------------------------------------------------------
    # Anzeige
    # ------------------------------------------------------------------

    def _append_rows(self, first_row, services):
        """Hängt Dienste unten an, ohne Neuaufbau."""
        self.table.setRowCount(first_row + len(services))

        for offset, service in enumerate(services):
            row = first_row + offset

            title_item = QTableWidgetItem(service.title)
            title_item.setData(Qt.ItemDataRole.UserRole, row)
            # Fremder Text, wörtlich anzeigen.
            title_item.setToolTip(plain_text_tooltip(
                f"{service.description}\n\n{service.url}".strip()
            ))

            type_item = QTableWidgetItem(type_label(service.type))
            reason = layer_loader.not_loadable_reason(service.type)
            if reason:
                type_item.setToolTip(reason)

            self.table.setItem(row, 0, title_item)
            self.table.setItem(row, 1, type_item)
            self.table.setItem(row, 2, QTableWidgetItem(service.provider))

    def _update_result_label(self, finished):
        shown = len(self._services)

        if not finished:
            if self._total:
                self.progress_bar.setRange(0, self._total)
                self.progress_bar.setValue(shown)
            self.result_label.setText(
                self.tr("{shown} von {total} Diensten werden geladen ...")
                .format(shown=shown, total=self._total)
            )
            return

        if shown == 0:
            if self._active_flags():
                self.result_label.setText(
                    self.tr("Kein Dienst mit den gewählten Kennzeichnungen.")
                )
            else:
                self.result_label.setText(self.tr("Kein Dienst gefunden."))
        elif shown < self._total:
            self.result_label.setText(
                self.tr("{shown} von {total} Diensten geladen")
                .format(shown=shown, total=self._total)
            )
        elif shown == 1:
            # Ohne Sprachdatei keine Pluralformen.
            self.result_label.setText(self.tr("1 Dienst"))
        else:
            self.result_label.setText(
                self.tr("{count} Dienste").format(count=shown)
            )

        self.result_label.setToolTip("")
        self.more_button.setVisible(shown < self._total)

    # ------------------------------------------------------------------
    # Auswahl und Aktionen
    # ------------------------------------------------------------------

    def _selected_service(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        title_item = self.table.item(row, 0)
        if title_item is None:
            return None
        return self._services[title_item.data(Qt.ItemDataRole.UserRole)]

    def _can_zoom(self, service):
        return (service is not None and service.bbox is not None
                and self._canvas is not None)

    def _on_selection_changed(self):
        service = self._selected_service()
        self.copy_button.setEnabled(
            service is not None and bool(service.url)
        )
        self.metadata_button.setEnabled(
            service is not None and bool(service.metadata_url)
        )
        self.zoom_button.setEnabled(self._can_zoom(service))
        self.load_button.setEnabled(service is not None)

    def _show_context_menu(self, position):
        """Rechtsklickmenü."""
        item = self.table.itemAt(position)
        if item is None:
            return
        self.table.selectRow(item.row())

        service = self._selected_service()
        if service is None:
            return

        menu = QMenu(self)
        load_action = menu.addAction(
            theme_icon("mActionAddWmsLayer.svg"), self.tr("Layer laden")
        )
        zoom_action = menu.addAction(
            theme_icon("mActionZoomToLayer.svg"), self.tr("Auf Dienst zoomen")
        )
        zoom_action.setEnabled(self._can_zoom(service))
        copy_action = menu.addAction(
            theme_icon("mActionEditCopy.svg"), self.tr("Dienst-URL kopieren")
        )
        copy_action.setEnabled(bool(service.url))
        metadata_action = menu.addAction(
            theme_icon("propertyicons/metadata.svg"),
            self.tr("Metadaten im Geoportal öffnen"),
        )
        metadata_action.setEnabled(bool(service.metadata_url))

        chosen = menu.exec(self.table.viewport().mapToGlobal(position))
        if chosen is load_action:
            self._load_selected()
        elif chosen is zoom_action:
            self._zoom_to_selected()
        elif chosen is copy_action:
            self._copy_selected_url()
        elif chosen is metadata_action:
            self._open_selected_metadata()

    def _copy_selected_url(self):
        service = self._selected_service()
        if service is None:
            return
        QApplication.clipboard().setText(service.url)
        self.result_label.setText(self.tr("URL in Zwischenablage kopiert."))

    def _open_selected_metadata(self):
        self._open_metadata(self._selected_service())

    def _open_metadata(self, service):
        """Öffnet die Detailansicht im Browser."""
        if service is None or not service.metadata_url:
            return
        if not QDesktopServices.openUrl(QUrl(service.metadata_url)):
            self.result_label.setText(
                self.tr("Browser konnte nicht geöffnet werden.")
            )

    def _zoom_to_selected(self):
        service = self._selected_service()
        if not self._can_zoom(service):
            return
        try:
            map_extent.zoom_to_bbox(self._canvas, service.bbox)
        except RuntimeError as error:
            self.result_label.setText(
                self.tr("Zoomen nicht möglich: {error}").format(error=error)
            )

    def _not_loadable_text(self, service):
        text = layer_loader.not_loadable_reason(service.type) or self.tr(
            "Die Art {type} kann nicht in QGIS geladen werden."
        ).format(type=type_label(service.type))
        if service.metadata_url:
            text += " " + self.tr(
                "Weitere Informationen stehen in den Metadaten im Geoportal."
            )
        return text

    def _explain_not_loadable(self, service):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(
            self.tr("{type} laden").format(type=type_label(service.type))
        )
        box.setText(self._not_loadable_text(service))

        open_button = None
        if service.metadata_url:
            open_button = box.addButton(
                self.tr("Metadaten öffnen"), QMessageBox.ButtonRole.AcceptRole
            )
            box.addButton(QMessageBox.StandardButton.Close)
            box.setDefaultButton(open_button)
        else:
            box.addButton(QMessageBox.StandardButton.Ok)

        box.exec()
        if open_button is not None and box.clickedButton() is open_button:
            self._open_metadata(service)
        box.deleteLater()

    def _load_selected(self, *args):
        service = self._selected_service()
        if service is None:
            return

        if not layer_loader.is_loadable(service.type):
            self._explain_not_loadable(service)
            return

        if not layer_loader.uses_source_dialog(service.type):
            self._start_tile_task(service)
            return

        try:
            layer_loader.open_source_dialog(
                service.type, service.title, service.url, self
            )
        except Exception as error:
            self._show_load_error(service.title, error)

    def _show_load_error(self, title, error):
        QMessageBox.critical(
            self,
            self.tr("Dienst laden fehlgeschlagen"),
            f"{title}\n\n{error}",
        )

    # ------------------------------------------------------------------
    # OGC API Tiles
    # ------------------------------------------------------------------

    def _start_tile_task(self, service):
        if self._tile_task is not None:
            self._tile_task.cancel()

        task = VectorTileInfoTask(service.url, service.title)
        self._tile_task = task
        task.taskCompleted.connect(self._on_tile_task_done)
        task.taskTerminated.connect(self._on_tile_task_failed)

        self.result_label.setText(self.tr("Kachelsatz wird ermittelt ..."))
        QgsApplication.taskManager().addTask(task)

    def _on_tile_task_done(self):
        """Legt den Kachel-Layer an."""
        task = self._tile_task
        if task is None or self.sender() is not task:
            return
        self._tile_task = None

        try:
            layer_loader.add_vector_tile_layer(
                task.template, task.zoom_min, task.zoom_max,
                task.layer_name,
            )
        except Exception as error:
            self.result_label.setText(self.tr("Kachel-Layer nicht geladen."))
            self._show_load_error(task.layer_name, error)
            return

        self.result_label.setText(
            self.tr("Layer geladen: {name}").format(name=task.layer_name)
        )

    def _on_tile_task_failed(self):
        task = self._tile_task
        if task is None or self.sender() is not task:
            return
        self._tile_task = None

        if task.error_message:
            self.result_label.setText(self.tr("Kachel-Layer nicht geladen."))
            self._show_load_error(task.layer_name, task.error_message)
        else:
            self.result_label.setText(
                self.tr("Kachelsatz-Ermittlung abgebrochen.")
            )
