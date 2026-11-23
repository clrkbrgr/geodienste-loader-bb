# -*- coding: utf-8 -*-
# Geodienste-Loader BB - QGIS-Plugin
# Copyright (C) 2026 Landesvermessung und Geobasisinformation Brandenburg
# SPDX-License-Identifier: GPL-3.0-or-later
"""Zoom des Kartenfensters auf die Ausdehnung eines Dienstes."""

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCsException,
    QgsProject,
    QgsRectangle,
)

_WGS84 = "EPSG:4326"

_POINT_MARGIN_DEGREES = 0.01


def zoom_to_bbox(canvas, bbox):
    """Zoomt auf ein Rechteck in EPSG:4326."""
    rect = QgsRectangle(*bbox)
    if rect.width() == 0 or rect.height() == 0:
        rect.grow(_POINT_MARGIN_DEGREES)

    transform = QgsCoordinateTransform(
        QgsCoordinateReferenceSystem(_WGS84),
        canvas.mapSettings().destinationCrs(),
        QgsProject.instance(),
    )
    try:
        target = transform.transformBoundingBox(rect)
    except QgsCsException as error:
        raise RuntimeError(str(error))

    canvas.setExtent(target)
    canvas.refresh()
