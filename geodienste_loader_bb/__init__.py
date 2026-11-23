# -*- coding: utf-8 -*-
# Geodienste-Loader BB - QGIS-Plugin
# Copyright (C) 2026 Landesvermessung und Geobasisinformation Brandenburg
# SPDX-License-Identifier: GPL-3.0-or-later
"""Einstiegspunkt des Plugins."""


def classFactory(iface):
    """Wird von QGIS beim Laden des Plugins aufgerufen."""
    # Übersetzung vor der Oberfläche laden.
    from .i18n import install_translator
    install_translator()

    from .plugin import GeodiensteLoaderPlugin
    return GeodiensteLoaderPlugin(iface)
