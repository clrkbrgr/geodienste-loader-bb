# -*- coding: utf-8 -*-
# Geodienste-Loader BB - QGIS-Plugin
# Copyright (C) 2026 Landesvermessung und Geobasisinformation Brandenburg
# SPDX-License-Identifier: GPL-3.0-or-later
"""Übersetzung der Oberfläche."""

import os

from qgis.PyQt.QtCore import QCoreApplication, QLocale, QTranslator
from qgis.core import QgsSettings

SOURCE_LANGUAGE = "de"

# Qt hält keine Referenz.
_translator = None


def current_locale():
    """Sprachcode von QGIS, z. B. "de_DE"."""
    settings = QgsSettings()
    if settings.value("locale/overrideFlag", False, type=bool):
        return settings.value("locale/userLocale", "", type=str)
    return QLocale.system().name()


def install_translator():
    """Lädt die Sprachdatei."""
    global _translator

    locale = current_locale()
    language = locale.split("_")[0]
    if not language or language == SOURCE_LANGUAGE:
        return

    folder = os.path.join(os.path.dirname(__file__), "i18n")
    for candidate in (locale, language):
        path = os.path.join(folder, f"geodienste_loader_bb_{candidate}.qm")
        if not os.path.exists(path):
            continue
        translator = QTranslator()
        if translator.load(path):
            QCoreApplication.installTranslator(translator)
            _translator = translator
            return


def remove_translator():
    """Entfernt die Sprachdatei beim Entladen."""
    global _translator
    if _translator is not None:
        QCoreApplication.removeTranslator(_translator)
        _translator = None
