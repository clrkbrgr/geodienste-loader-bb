# -*- coding: utf-8 -*-
# Geodienste-Loader BB - QGIS-Plugin
# Copyright (C) 2026 Landesvermessung und Geobasisinformation Brandenburg
# SPDX-License-Identifier: GPL-3.0-or-later
"""Helfer für ein einheitliches Aussehen ohne feste Farben."""

import html
import os

from qgis.PyQt.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QFrame,
    QHeaderView,
    QLayout,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QWidget,
)
from qgis.core import QgsApplication, QgsSettings

MARGIN = 8
SPACING = 6


def apply_layout_style(layout, margin=MARGIN, spacing=SPACING):
    """Setzt Rand und Abstand eines Layouts."""
    layout.setContentsMargins(margin, margin, margin, margin)
    layout.setSpacing(spacing)
    return layout


def plain_text_tooltip(text):
    """Tooltip mit fremdem Text, wörtlich angezeigt."""
    if not text:
        return ""
    escaped = html.escape(str(text)).replace("\n", "<br>")
    return f"<qt>{escaped}</qt>"


def theme_icon(name):
    """Symbol aus dem QGIS-Thema."""
    return QgsApplication.getThemeIcon(f"/{name}")


def plugin_icon():
    """Symbol des Plugins."""
    return QIcon(os.path.join(os.path.dirname(__file__), "icon.png"))


class FlowLayout(QLayout):
    """Setzt Widgets nebeneinander mit Umbruch."""

    def __init__(self, parent=None, spacing=4):
        super().__init__(parent)
        self._items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(),
                      margins.top() + margins.bottom())
        return size

    def _arrange(self, rect, test_only):
        """Ordnet die Widgets an und liefert die Höhe."""
        x = rect.x()
        y = rect.y()
        line_height = 0

        for item in self._items:
            widget = item.widget()
            if widget is not None and widget.isHidden():
                # Im verdeckten Reiter ist isVisible() False.
                continue

            item_size = item.sizeHint()
            next_x = x + item_size.width() + self.spacing()

            if next_x - self.spacing() > rect.right() and line_height > 0:
                x = rect.x()
                y = y + line_height + self.spacing()
                next_x = x + item_size.width() + self.spacing()
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item_size))

            x = next_x
            line_height = max(line_height, item_size.height())

        return y + line_height - rect.y()


# palette() folgt dem aktiven Thema.
FILTER_BUTTON_STYLE = """
QToolButton {
    padding: 2px 6px;
    border: 1px solid palette(mid);
    border-radius: 3px;
}
QToolButton:hover {
    border-color: palette(highlight);
}
QToolButton:checked {
    background-color: palette(highlight);
    color: palette(highlighted-text);
    border-color: palette(highlight);
}
"""


def make_filter_button(text, tooltip=""):
    """Umschaltbarer Button für Filter."""
    button = QToolButton()
    button.setText(text)
    button.setCheckable(True)
    button.setStyleSheet(FILTER_BUTTON_STYLE)
    button.setSizePolicy(QSizePolicy.Policy.Fixed,
                         QSizePolicy.Policy.Fixed)
    if tooltip:
        button.setToolTip(tooltip)
    return button


def make_filter_checkbox(text, tooltip=""):
    """Checkbox für Filter."""
    checkbox = QCheckBox(text)
    checkbox.setSizePolicy(QSizePolicy.Policy.Fixed,
                           QSizePolicy.Policy.Fixed)
    if tooltip:
        checkbox.setToolTip(tooltip)
    return checkbox


def make_icon_button(icon_name, tooltip, fallback_text):
    """Knopf nur mit Symbol."""
    button = QPushButton()
    icon = theme_icon(icon_name)
    if icon.isNull():
        button.setText(fallback_text)
    else:
        button.setIcon(icon)
    button.setToolTip(tooltip)
    button.setAccessibleName(tooltip)
    return button


class FlowWidget(QWidget):
    """Behälter für ein FlowLayout."""

    def __init__(self, parent=None, spacing=4):
        super().__init__(parent)
        self.flow_layout = FlowLayout(self, spacing=spacing)

        policy = QSizePolicy(QSizePolicy.Policy.Preferred,
                             QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.flow_layout.heightForWidth(width)

    def addWidget(self, widget):
        self.flow_layout.addWidget(widget)

    def refresh(self):
        """Rechnet das Layout neu."""
        self.flow_layout.invalidate()
        self.updateGeometry()


def make_separator(height=18):
    """Senkrechter Trennstrich."""
    separator = QFrame()
    separator.setFrameShape(QFrame.Shape.VLine)
    separator.setFrameShadow(QFrame.Shadow.Sunken)
    separator.setFixedSize(2, height)
    return separator


def setup_table_header(table, default_widths, settings_key,
                       stretch_column=0):
    """Spaltenköpfe einrichten und gespeicherte Breiten laden."""
    header = table.horizontalHeader()
    header.setSectionsMovable(True)
    header.setMinimumSectionSize(48)
    header.setStretchLastSection(False)

    table.setTextElideMode(Qt.TextElideMode.ElideRight)

    stored = QgsSettings().value(settings_key)
    if stored:
        header.restoreState(stored)

    # Stretch würde die Spalte sperren.
    for index, width in enumerate(default_widths):
        header.setSectionResizeMode(
            index, QHeaderView.ResizeMode.Interactive
        )
        if width and not stored:
            table.setColumnWidth(index, width)

    # Qt hält keine Referenz.
    table._stretch_helper = _StretchHelper(table, stretch_column)

    return header


class _StretchHelper(QObject):
    """Lässt eine Spalte mitwachsen."""

    def __init__(self, table, column):
        super().__init__(table)
        self._table = table
        self._column = column
        self._resized_by_user = False
        # Signal kommt dann nicht vom Nutzer.
        self._setting_width = False

        table.viewport().installEventFilter(self)
        table.horizontalHeader().sectionResized.connect(
            self._on_section_resized
        )

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            self.apply()
        return False

    def _on_section_resized(self, index, old_width, new_width):
        if self._setting_width:
            return
        if index == self._column:
            self._resized_by_user = True
        else:
            self.apply()

    def apply(self):
        """Setzt die Breite der mitwachsenden Spalte."""
        if self._resized_by_user:
            return

        header = self._table.horizontalHeader()
        used_width = sum(
            header.sectionSize(index)
            for index in range(header.count())
            if index != self._column and not header.isSectionHidden(index)
        )
        free_width = self._table.viewport().width() - used_width
        if free_width < header.minimumSectionSize():
            return

        self._setting_width = True
        self._table.setColumnWidth(self._column, free_width)
        self._setting_width = False


def save_table_state(table, settings_key):
    """Speichert Breite und Reihenfolge der Spalten."""
    QgsSettings().setValue(
        settings_key, table.horizontalHeader().saveState()
    )
