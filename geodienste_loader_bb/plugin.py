# -*- coding: utf-8 -*-
# Geodienste-Loader BB - QGIS-Plugin
# Copyright (C) 2026 Landesvermessung und Geobasisinformation Brandenburg
# SPDX-License-Identifier: GPL-3.0-or-later
"""Plugin-Klasse: Menüeintrag, Werkzeugleiste und Bedienfeld."""

from qgis.PyQt.QtCore import QCoreApplication, Qt

# QAction: Qt6 in QtGui, Qt5 in QtWidgets.
try:
    from qgis.PyQt.QtGui import QAction
except ImportError:
    from qgis.PyQt.QtWidgets import QAction

from .i18n import remove_translator
from .main_dock import MainDock
from .ui_helpers import plugin_icon

PLUGIN_NAME = "Geodienste-Loader BB"


class GeodiensteLoaderPlugin:

    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dock = None

    def initGui(self):
        self.action = QAction(
            plugin_icon(), PLUGIN_NAME, self.iface.mainWindow()
        )
        self.action.setToolTip(
            QCoreApplication.translate(
                "GeodiensteLoaderBB",
                "Diensteanbieter und Geodienste der GDI Brandenburg",
            )
        )
        self.action.setCheckable(True)
        # toggled feuert auch beim Reiterwechsel.
        self.action.triggered.connect(self._toggle_dock)

        self.iface.addPluginToWebMenu(PLUGIN_NAME, self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        self.iface.removePluginWebMenu(PLUGIN_NAME, self.action)
        self.iface.removeToolBarIcon(self.action)

        if self.dock is not None:
            # Erst Abfragen abbrechen, dann löschen.
            self.dock.cleanup()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None

        remove_translator()

    def _toggle_dock(self, checked):
        """Zeigt oder versteckt das Dock."""
        if self.dock is None:
            self.dock = MainDock(
                self.iface.mainWindow(), self.iface.mapCanvas()
            )
            self.iface.addDockWidget(
                Qt.DockWidgetArea.RightDockWidgetArea, self.dock
            )
            self.dock.visibilityChanged.connect(self.action.setChecked)

        self.dock.setVisible(checked)
        if checked:
            self.dock.raise_()
