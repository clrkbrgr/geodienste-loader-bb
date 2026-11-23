# -*- coding: utf-8 -*-
# Geodienste-Loader BB - QGIS-Plugin
# Copyright (C) 2026 Landesvermessung und Geobasisinformation Brandenburg
# SPDX-License-Identifier: GPL-3.0-or-later
"""Dienste als Layer laden."""

from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtWidgets import QDialog, QVBoxLayout
from qgis.core import (
    Qgis,
    QgsOwsConnection,
    QgsProject,
    QgsProviderRegistry,
    QgsRasterLayer,
    QgsSettings,
    QgsVectorLayer,
    QgsVectorTileLayer,
    QgsCoordinateReferenceSystem,
)
from qgis.gui import QgsGui, QgsMessageBar
from qgis.utils import iface

from .compat import enum_value, is_qgis_4_or_newer

# QGIS schreibt die Schlüssel uneinheitlich.
SOURCE_SELECT_KEYS_FOR_TYPE = {
    "WMS": ["wms", "WMS"],
    "WMTS": ["wms", "WMS"],
    "WFS": ["WFS", "wfs"],
    "OAF": ["WFS", "wfs"],
    "WCS": ["wcs", "WCS"],
}

CONNECTION_SERVICE_FOR_TYPE = {
    "WMS": "wms",
    "WMTS": "wms",
    "WFS": "wfs",
    "OAF": "wfs",
    "WCS": "wcs",
}

DIRECT_LOAD_TYPES = {"OAT"}

# Ohne SERVICE und REQUEST antwortet WMTS mit HTTP 400.
_TYPES_KEEPING_FULL_CAPABILITIES_URL = {"WMTS"}

# Hängt QGIS selbst an.
_OWS_PARAMS_TO_STRIP = {"service", "request", "version"}

_KEY_PATTERN_CANDIDATES = [
    "connections/ows/items/{service}/connections/items/{name}",
    "qgis/connections-{service}/{name}",
]

CONNECTION_NAME_PREFIX = "Geodienste-Loader BB: "

DEFAULT_PROJECT_CRS = "EPSG:25833"


def ensure_project_crs():
    """Setzt in einem leeren Projekt EPSG:25833 vor dem ersten Layer."""
    project = QgsProject.instance()
    if not project.mapLayers():
        project.setCrs(QgsCoordinateReferenceSystem(DEFAULT_PROJECT_CRS))


_verified_patterns = {}


def not_loadable_reason(service_type):
    """Grund für eine nicht ladbare Art, sonst None."""
    # Ein translate() je Text für lupdate.
    if service_type == "CSW":
        return QCoreApplication.translate(
            "GeodiensteLoaderBB",
            "Ein Katalogdienst (CSW) kann nicht in QGIS geladen werden."
        )
    if service_type == "ATOM":
        return QCoreApplication.translate(
            "GeodiensteLoaderBB",
            "Ein ATOM-Feed kann nicht in QGIS geladen werden."
        )
    if service_type == "REST":
        return QCoreApplication.translate(
            "GeodiensteLoaderBB",
            "Eine REST-Schnittstelle kann nicht in QGIS geladen werden."
        )
    if service_type == "UNKNOWN":
        return QCoreApplication.translate(
            "GeodiensteLoaderBB",
            "Ein Dienst ohne angegebene Art kann nicht in QGIS geladen werden."
        )
    return None


def is_loadable(service_type):
    """True, wenn sich die Art als Layer laden lässt."""
    return (service_type in SOURCE_SELECT_KEYS_FOR_TYPE
            or service_type in DIRECT_LOAD_TYPES)


def uses_source_dialog(service_type):
    """True, wenn QGIS für die Art einen Quelldialog hat."""
    return service_type in SOURCE_SELECT_KEYS_FOR_TYPE


def prepare_url(service_type, url):
    """Dienst-URL für die Verbindung."""
    parts = urlsplit(url)
    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in _OWS_PARAMS_TO_STRIP
    ]

    if service_type in _TYPES_KEEPING_FULL_CAPABILITIES_URL:
        kept.append(("SERVICE", service_type))
        kept.append(("REQUEST", "GetCapabilities"))

    return urlunsplit((
        parts.scheme, parts.netloc, parts.path,
        urlencode(kept), parts.fragment,
    ))


def sanitize_connection_name(name):
    """Verbindungsname mit Präfix, ohne "/", höchstens 80 Zeichen."""
    # "/" erzeugt in den Einstellungen eine Untergruppe.
    cleaned = name.replace("/", "-").replace("\\", "-").strip()
    if len(cleaned) > 80:
        cleaned = cleaned[:77] + "..."
    return CONNECTION_NAME_PREFIX + cleaned


def _discover_pattern(target_service):
    """Pfad einer vorhandenen Verbindung als Muster, oder None."""
    settings = QgsSettings()
    all_keys = settings.allKeys()

    services = [target_service] + [
        s for s in ("wms", "wfs", "wcs") if s != target_service
    ]

    for service in services:
        for reference_name in QgsOwsConnection.connectionList(service):
            needle = f"/{reference_name}/url"
            for key in all_keys:
                if not key.endswith(needle):
                    continue

                # Name zuerst, er kann "wms" enthalten.
                pattern = key[: -len("/url")]
                pattern = pattern.replace(reference_name, "{name}")
                pattern = pattern.replace(service, "{service}")
                pattern = pattern.replace(service.upper(), "{service}")

                if "{service}" in pattern and "{name}" in pattern:
                    return pattern

    return None


def _write_connection(pattern, provider_key, connection_name, url):
    base_key = pattern.format(service=provider_key, name=connection_name)
    settings = QgsSettings()
    settings.setValue(f"{base_key}/url", url)
    # Der Quelldialog liest sofort.
    settings.sync()
    return base_key


def _remove_connection_key(base_key):
    settings = QgsSettings()
    settings.remove(base_key)
    settings.sync()


def _connection_has_url(provider_key, connection_name, url):
    """True, wenn die Verbindung mit dieser URL existiert."""
    if connection_name not in QgsOwsConnection.connectionList(provider_key):
        return False
    connection = QgsOwsConnection(provider_key, connection_name)
    return connection.uri().param("url") == url


def ensure_connection(provider_key, connection_name, url):
    """
    Legt eine OWS-Verbindung an und wählt sie aus.

    :return: (base_key, created)
    """
    existed_before = (
        connection_name in QgsOwsConnection.connectionList(provider_key)
    )

    if existed_before and _connection_has_url(
        provider_key, connection_name, url
    ):
        QgsOwsConnection.setSelectedConnection(provider_key, connection_name)
        return None, False

    created = not existed_before

    cached = _verified_patterns.get(provider_key)
    if cached:
        base_key = _write_connection(
            cached, provider_key, connection_name, url
        )
        if _connection_has_url(provider_key, connection_name, url):
            QgsOwsConnection.setSelectedConnection(
                provider_key, connection_name
            )
            return base_key, created

    patterns = []
    discovered = _discover_pattern(provider_key)
    if discovered:
        patterns.append(discovered)
    patterns.extend(_KEY_PATTERN_CANDIDATES)

    for pattern in patterns:
        base_key = _write_connection(
            pattern, provider_key, connection_name, url
        )
        if _connection_has_url(provider_key, connection_name, url):
            _verified_patterns[provider_key] = pattern
            QgsOwsConnection.setSelectedConnection(
                provider_key, connection_name
            )
            return base_key, created
        _remove_connection_key(base_key)

    raise RuntimeError(
        QCoreApplication.translate(
            "GeodiensteLoaderBB",
            "Die Verbindung \"{name}\" ließ sich nicht in QGIS anlegen.\n\n"
            "Abhilfe: im Bedienfeld Browser einmal von Hand eine "
            "WMS-Verbindung anlegen (Rechtsklick auf WMS/WMTS > Neue "
            "Verbindung) und den Dienst erneut laden."
        ).format(name=connection_name)
    )


def _add_raster_layer(uri, base_name, provider_key):
    layer = QgsRasterLayer(uri, base_name, provider_key)
    QgsProject.instance().addMapLayer(layer)


def _add_vector_layer(uri, base_name, provider_key):
    layer = QgsVectorLayer(uri, base_name, provider_key)
    QgsProject.instance().addMapLayer(layer)


def _add_layer_to_project(layer_type, uri, base_name, provider_key):
    """Slot für addLayer (nur QGIS 4)."""
    if layer_type == enum_value(Qgis, "LayerType", "Raster"):
        _add_raster_layer(uri, base_name, provider_key)
    elif layer_type == enum_value(Qgis, "LayerType", "Vector"):
        _add_vector_layer(uri, base_name, provider_key)


def _connect_add_layer_signals(widget):
    """
    Verbindet den Quelldialog mit dem Anlegen der Layer.

    PyQt5 kann addLayer nicht zustellen (Enum-Fehler). Deshalb unter QGIS 3
    addRasterLayer und addVectorLayer. Nie beide verbinden.
    """
    if is_qgis_4_or_newer():
        widget.addLayer.connect(_add_layer_to_project)
    else:
        widget.addRasterLayer.connect(_add_raster_layer)
        widget.addVectorLayer.connect(_add_vector_layer)


def manual_step_hint(service_type):
    """Hinweis für WFS und OGC API Features (QGIS-Issue 52228), sonst None."""
    if service_type == "OAF":
        return QCoreApplication.translate(
            "GeodiensteLoaderBB",
            "Bleibt die Liste nach \"Verbinden\" leer: im Dialog auf "
            "\"Bearbeiten\" gehen und die Version auf "
            "\"OGC API - Features\" stellen.",
        )
    return None


def _create_selection_widget(service_type, parent):
    """Quelldialog von QGIS für eine Diensteart."""
    registry = QgsGui.sourceSelectProviderRegistry()
    for key in SOURCE_SELECT_KEYS_FOR_TYPE[service_type]:
        widget = registry.createSelectionWidget(
            key,
            parent,
            Qt.WindowType.Widget,
            enum_value(QgsProviderRegistry, "WidgetMode", "Embedded"),
        )
        if widget is not None:
            return widget

    raise RuntimeError(
        QCoreApplication.translate(
            "GeodiensteLoaderBB",
            "QGIS bietet für {type} keinen Dialog zum Laden an."
        ).format(type=service_type)
    )


def build_source_dialog(service_type, title, parent):
    """Baut das Fenster mit dem Quelldialog."""
    widget = _create_selection_widget(service_type, parent)
    _connect_add_layer_signals(widget)

    dialog = QDialog(parent)
    dialog.setWindowTitle(
        QCoreApplication.translate(
            "GeodiensteLoaderBB", "{type} laden: {name}"
        ).format(type=service_type, name=title)
    )
    layout = QVBoxLayout(dialog)

    hint = manual_step_hint(service_type)
    if hint:
        hint_bar = QgsMessageBar(dialog)
        hint_bar.pushMessage(
            hint, enum_value(Qgis, "MessageLevel", "Info"), 0
        )
        layout.addWidget(hint_bar)

    layout.addWidget(widget, 1)

    # "Schließen" blendet nur das Widget aus.
    widget.rejected.connect(dialog.reject)

    dialog.resize(900, 600)
    return dialog


def _remove_temporary_connection(provider_key, base_key, previous_selection):
    """Entfernt die angelegte Verbindung."""
    _remove_connection_key(base_key)
    QgsOwsConnection.setSelectedConnection(provider_key, previous_selection)

    # Sonst zeigt der Browser den Eintrag bis zum Neustart.
    if iface is not None:
        iface.reloadConnections()


def open_source_dialog(service_type, title, url, parent):
    """Öffnet das Ladefenster modal."""
    provider_key = CONNECTION_SERVICE_FOR_TYPE[service_type]
    connection_name = sanitize_connection_name(title)

    previous_selection = QgsOwsConnection.selectedConnection(provider_key)

    ensure_project_crs()
    base_key, created = ensure_connection(
        provider_key,
        connection_name,
        prepare_url(service_type, url),
    )

    dialog = None
    try:
        dialog = build_source_dialog(service_type, title, parent)
        dialog.exec()
    finally:
        if created:
            _remove_temporary_connection(
                provider_key, base_key, previous_selection
            )

        if dialog is not None:
            dialog.deleteLater()


# ----------------------------------------------------------------------
# OGC API Tiles
# ----------------------------------------------------------------------


def add_vector_tile_layer(template, zoom_min, zoom_max, layer_name):
    """Legt einen Vektorkachel-Layer an."""
    # Kodieren, sonst trennt QGIS am "?".
    uri = (
        f"type=xyz&url={quote(template, safe='')}"
        f"&zmin={zoom_min}&zmax={zoom_max}"
    )

    layer = QgsVectorTileLayer(uri, layer_name)
    if not layer.isValid():
        raise RuntimeError(
            QCoreApplication.translate(
                "GeodiensteLoaderBB",
                "Der Kachel-Layer konnte nicht erzeugt werden.\n"
                "Vorlage: {template}",
            ).format(template=template)
        )
    ensure_project_crs()
    QgsProject.instance().addMapLayer(layer)
