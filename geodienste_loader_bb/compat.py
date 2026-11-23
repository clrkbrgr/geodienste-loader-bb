# -*- coding: utf-8 -*-
# Geodienste-Loader BB - QGIS-Plugin
# Copyright (C) 2026 Landesvermessung und Geobasisinformation Brandenburg
# SPDX-License-Identifier: GPL-3.0-or-later
"""Hilfe für QGIS 3 (Qt5) und QGIS 4 (Qt6)."""

from qgis.core import Qgis

# Erste Version von QGIS 4.
_QGIS_4_VERSION_INT = 40000


def enum_value(owner, enum_name, member):
    """Enum-Wert für QGIS 3 und 4."""
    enum_type = getattr(owner, enum_name, None)
    if enum_type is not None and hasattr(enum_type, member):
        return getattr(enum_type, member)

    return getattr(owner, member)


def is_qgis_4_or_newer():
    """True ab QGIS 4 (Qt6)."""
    return Qgis.QGIS_VERSION_INT >= _QGIS_4_VERSION_INT
