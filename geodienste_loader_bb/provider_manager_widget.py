# -*- coding: utf-8 -*-
# Geodienste-Loader BB - QGIS-Plugin
# Copyright (C) 2026 Landesvermessung und Geobasisinformation Brandenburg
# SPDX-License-Identifier: GPL-3.0-or-later
"""Reiter "Diensteanbieter"."""

from qgis.PyQt.QtCore import QLocale, QStringListModel, Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCompleter,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsSettings
from qgis.gui import QgsFilterLineEdit

from .providers import ALL_CATEGORIES, category_label, filter_providers
from .ui_helpers import (
    FlowWidget,
    apply_layout_style,
    make_filter_checkbox,
    make_icon_button,
    plain_text_tooltip,
    save_table_state,
    setup_table_header,
    theme_icon,
)

SETTINGS_PREFIX = "geodienste_loader_bb/anbieter/"
COLUMNS_SETTINGS_KEY = SETTINGS_PREFIX + "spalten"

COLUMN_NAME, COLUMN_FUNCTION, COLUMN_COUNT = range(3)


class ProviderManagerWidget(QWidget):

    # (Kennung, Name)
    provider_selected = pyqtSignal(str, str)

    refresh_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._all_providers = []
        self._providers_by_key = {}
        self._visible_providers = []
        self._generated = None
        self._settings = QgsSettings()

        self._build_ui()
        self._restore_checkbox_state()
        self._connect_signals()

    # ------------------------------------------------------------------
    # Aufbau
    # ------------------------------------------------------------------

    def _build_ui(self):
        layout = apply_layout_style(QVBoxLayout(self))

        self.name_edit = QgsFilterLineEdit()
        self.name_edit.setPlaceholderText(self.tr("Name des Diensteanbieters"))
        self.name_edit.setShowSearchIcon(True)

        self._completion_model = QStringListModel(self)
        completer = QCompleter(self._completion_model, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        # "barnim" findet auch "Barnim-Oderbruch".
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setMaxVisibleItems(10)
        self.name_edit.setCompleter(completer)
        self._completer = completer

        search_layout = QHBoxLayout()
        search_layout.setSpacing(6)
        search_layout.addWidget(self.name_edit, 1)

        self.refresh_button = make_icon_button(
            "mActionRefresh.svg", "", self.tr("Aktualisieren"),
        )
        search_layout.addWidget(self.refresh_button)

        layout.addLayout(search_layout)

        self.category_bar = FlowWidget(spacing=12)
        self.category_buttons = {}
        for category in ALL_CATEGORIES:
            checkbox = make_filter_checkbox(
                category_label(category),
                self.tr(
                    "Diensteanbieter der Art \"{category}\" anzeigen"
                ).format(
                    category=category_label(category)
                ),
            )
            checkbox.setChecked(True)
            self.category_bar.addWidget(checkbox)
            self.category_buttons[category] = checkbox

        layout.addWidget(self.category_bar)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([
            self.tr("Name"),
            self.tr("Art"),
            self.tr("Dienste"),
        ])
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

        # Vor restoreState(), sonst sortiert Qt absteigend.
        self.table.horizontalHeader().setSortIndicator(
            COLUMN_NAME, Qt.SortOrder.AscendingOrder
        )
        header = setup_table_header(
            self.table, [None, 150, 60], COLUMNS_SETTINGS_KEY
        )
        header.setHighlightSections(False)

        layout.addWidget(self.table)

        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(6)
        footer_layout.addStretch(1)

        self.show_services_button = QPushButton(self.tr("Dienste anzeigen"))
        self.show_services_button.setIcon(
            theme_icon("mActionAddWmsLayer.svg")
        )
        self.show_services_button.setToolTip(
            self.tr("Zeigt die Dienste des gewählten Diensteanbieters.")
        )
        self.show_services_button.setEnabled(False)
        footer_layout.addWidget(self.show_services_button)

        layout.addLayout(footer_layout)

        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        self.result_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(self.result_label)

    def _connect_signals(self):
        self.name_edit.textChanged.connect(self._apply_filter)
        self._completer.activated.connect(self._on_completion_chosen)
        self.name_edit.returnPressed.connect(self._on_search_confirmed)

        for button in self.category_buttons.values():
            button.toggled.connect(self._on_category_toggled)

        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        self.table.itemDoubleClicked.connect(self._emit_selected_provider)
        self.show_services_button.clicked.connect(
            self._emit_selected_provider
        )
        self.refresh_button.clicked.connect(self.refresh_requested.emit)

    # ------------------------------------------------------------------
    # Öffentliche Methoden
    # ------------------------------------------------------------------

    def set_providers(self, providers, generated=None):
        """Setzt die Anbieterliste."""
        self._all_providers = providers
        self._providers_by_key = {p.key: p for p in providers}
        self._generated = generated
        self._completion_model.setStringList(
            [provider.display_name for provider in providers]
        )
        self._apply_filter()

    def _on_completion_chosen(self, text):
        """Vorschlag gewählt: Anbieter auswählen."""
        provider = self._find_provider(text)
        if provider is not None:
            self._ensure_category_active(provider.category)

        self._apply_filter()
        if provider is not None:
            self._select_key(provider.key)
        elif len(self._visible_providers) == 1:
            self.table.selectRow(0)

    def _on_search_confirmed(self):
        self._on_completion_chosen(self.name_edit.text())

    def _find_provider(self, text):
        """Anbieter mit genau diesem Namen, oder None."""
        text = text.strip()
        for provider in self._all_providers:
            if text in (provider.display_name, provider.name):
                return provider
        return None

    def _ensure_category_active(self, category):
        """Schaltet eine Kategorie ein."""
        button = self.category_buttons.get(category)
        if button is not None and not button.isChecked():
            button.setChecked(True)

    def _selected_key(self):
        row = self.table.currentRow()
        if row < 0 or not self.table.selectedItems():
            return None
        item = self.table.item(row, COLUMN_NAME)
        return None if item is None else item.data(Qt.ItemDataRole.UserRole)

    def _select_key(self, key):
        """Wählt die Zeile eines Anbieters aus."""
        if key is None:
            return False
        for row in range(self.table.rowCount()):
            item = self.table.item(row, COLUMN_NAME)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == key:
                self.table.selectRow(row)
                self.table.scrollToItem(item)
                return True
        return False

    def update_service_count(self, provider_key, count):
        """Schreibt die tatsächliche Dienstezahl."""
        provider = self._providers_by_key.get(provider_key)
        if provider is not None:
            provider.service_count = count

        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, COLUMN_NAME)
            if name_item is None:
                continue
            if name_item.data(Qt.ItemDataRole.UserRole) != provider_key:
                continue

            count_item = self.table.item(row, COLUMN_COUNT)
            if count_item is not None:
                count_item.setData(Qt.ItemDataRole.DisplayRole, count)
            return

    def cleanup(self):
        """Sichert die Spaltenbreiten."""
        save_table_state(self.table, COLUMNS_SETTINGS_KEY)

    def set_refresh_tooltip(self, text):
        self.refresh_button.setToolTip(text)
        # Der Tooltip ist auch der Name für Screenreader.
        self.refresh_button.setAccessibleName(text)

    def set_busy(self, busy, message=""):
        """Sperrt den Knopf und zeigt eine Meldung."""
        self.refresh_button.setEnabled(not busy)
        if message:
            self.result_label.setText(message)

    # ------------------------------------------------------------------
    # Filter und Anzeige
    # ------------------------------------------------------------------

    def _active_categories(self):
        return {
            category
            for category, button in self.category_buttons.items()
            if button.isChecked()
        }

    def _apply_filter(self):
        self._visible_providers = filter_providers(
            self._all_providers,
            self.name_edit.text(),
            self._active_categories(),
        )
        self._fill_table()

    @staticmethod
    def _number_item(value):
        """Zelle mit sortierbarer Zahl."""
        item = QTableWidgetItem()
        item.setData(Qt.ItemDataRole.DisplayRole, value)
        item.setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        return item

    def _fill_table(self):
        selected_key = self._selected_key()

        # Beim Befüllen nicht sortieren.
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._visible_providers))

        for row, provider in enumerate(self._visible_providers):
            # Kennung am Item, Zeilen verschieben sich beim Sortieren.
            name_item = QTableWidgetItem(provider.display_name)
            name_item.setData(Qt.ItemDataRole.UserRole, provider.key)
            if provider.display_name != provider.name:
                name_item.setToolTip(plain_text_tooltip(provider.name))

            function_item = QTableWidgetItem(
                provider.function or category_label(provider.category)
            )
            function_item.setToolTip(category_label(provider.category))

            self.table.setItem(row, COLUMN_NAME, name_item)
            self.table.setItem(row, COLUMN_FUNCTION, function_item)
            self.table.setItem(
                row, COLUMN_COUNT, self._number_item(provider.service_count)
            )

        header = self.table.horizontalHeader()
        self.table.setSortingEnabled(True)
        self.table.sortItems(
            header.sortIndicatorSection(), header.sortIndicatorOrder()
        )

        self._update_result_label()
        if not self._select_key(selected_key):
            self.table.clearSelection()
        self._on_selection_changed()

    def _update_result_label(self):
        total = len(self._all_providers)
        shown = len(self._visible_providers)

        if shown == 0 and total > 0:
            if not self._active_categories():
                self.result_label.setText(self.tr("Keine Art ausgewählt."))
                return

            hidden_count = self._hidden_by_category_count()
            if hidden_count:
                self.result_label.setText(
                    self.tr(
                        "Kein Treffer in der gewählten Art. "
                        "{count} Treffer in anderen Arten."
                    ).format(count=hidden_count)
                )
            else:
                self.result_label.setText(
                    self.tr("Kein Diensteanbieter gefunden.")
                )
            return

        if shown == total:
            text = self.tr("{total} Diensteanbieter").format(total=total)
        else:
            text = self.tr("{shown} von {total} Diensteanbietern").format(
                shown=shown, total=total
            )

        if self._generated is not None:
            local_date = QLocale().toString(
                self._generated.astimezone().date(),
                QLocale.FormatType.ShortFormat,
            )
            text += self.tr(" (Stand {date})").format(date=local_date)

        self.result_label.setText(text)

    # ------------------------------------------------------------------
    # Auswahl
    # ------------------------------------------------------------------

    def _hidden_by_category_count(self):
        """Nur vom Kategoriefilter ausgeblendete Treffer."""
        return len(filter_providers(
            self._all_providers,
            self.name_edit.text(),
            set(ALL_CATEGORIES),
        ))

    def _on_selection_changed(self):
        self.show_services_button.setEnabled(
            len(self.table.selectedItems()) > 0
        )

    def _emit_selected_provider(self, *args):
        provider = self._providers_by_key.get(self._selected_key())
        if provider is None:
            return
        self.provider_selected.emit(provider.key, provider.name)

    # ------------------------------------------------------------------
    # Kategorieauswahl speichern
    # ------------------------------------------------------------------

    def _on_category_toggled(self):
        for category, button in self.category_buttons.items():
            self._settings.setValue(
                SETTINGS_PREFIX + category, button.isChecked()
            )
        self._apply_filter()

    def _restore_checkbox_state(self):
        """Vor dem Verbinden der Signale aufrufen."""
        for category, button in self.category_buttons.items():
            button.setChecked(self._settings.value(
                SETTINGS_PREFIX + category, defaultValue=True, type=bool
            ))
