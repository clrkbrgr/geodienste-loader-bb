# -*- coding: utf-8 -*-
# Geodienste-Loader BB - QGIS-Plugin
# Copyright (C) 2026 Landesvermessung und Geobasisinformation Brandenburg
# SPDX-License-Identifier: GPL-3.0-or-later
"""Netzzugriff über QGIS und dessen Proxy."""

import json
from urllib.parse import urlsplit

from qgis.core import Qgis, QgsBlockingNetworkRequest, QgsMessageLog
from qgis.PyQt.QtCore import QCoreApplication, QUrl
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest

from .compat import enum_value

LOG_TAG = "Geodienste-Loader BB"


class ServiceError(RuntimeError):
    """Abruf gescheitert. detail enthält die technische Angabe."""

    def __init__(self, message, detail=""):
        super().__init__(message)
        self.detail = detail


def fetch_json(url):
    """GET, Antwort als JSON."""
    request = QNetworkRequest(QUrl(url))
    request.setRawHeader(b"Accept", b"application/json")

    blocking_request = QgsBlockingNetworkRequest()
    return _evaluate_reply(
        blocking_request, blocking_request.get(request), url
    )


def post_json(url, payload):
    """POST mit JSON, Antwort als JSON."""
    request = QNetworkRequest(QUrl(url))
    request.setRawHeader(b"Accept", b"application/json")
    request.setRawHeader(b"Content-Type", b"application/json")

    body = json.dumps(payload).encode("utf-8")

    blocking_request = QgsBlockingNetworkRequest()
    return _evaluate_reply(
        blocking_request, blocking_request.post(request, body), url
    )


HTTP_SERVER_ERROR = "server"
HTTP_NOT_FOUND = "not_found"
HTTP_REJECTED = "rejected"

_QT_SERVER_ERRORS = {
    "InternalServerError": 500,
    "OperationNotImplementedError": 501,
    "ServiceUnavailableError": 503,
    "UnknownServerError": None,
}

# 401 und 407 fehlen bewusst.
_QT_CONTENT_ERRORS = {
    "ProtocolInvalidOperationError": 400,
    "ContentAccessDenied": 403,
    "ContentNotFoundError": 404,
    "ContentOperationNotPermittedError": 405,
    "ContentConflictError": 409,
    "ContentGoneError": 410,
    "UnknownContentError": None,
}

_AUTH_STATUS = {401, 407}


def _http_status(blocking_request):
    """HTTP-Status der Antwort. Kann aus dem Cache veraltet sein."""
    reply = blocking_request.reply()
    if reply is None:
        return None
    status = reply.attribute(
        enum_value(QNetworkRequest, "Attribute", "HttpStatusCodeAttribute")
    )
    try:
        return int(status)
    except (TypeError, ValueError):
        return None


def _qt_error_name(blocking_request):
    """Name des Qt-Fehlercodes."""
    reply = blocking_request.reply()
    if reply is None:
        return None
    code = reply.error()
    for name in list(_QT_SERVER_ERRORS) + list(_QT_CONTENT_ERRORS):
        try:
            if code == enum_value(QNetworkReply, "NetworkError", name):
                return name
        except AttributeError:
            continue
    return None


def _http_error_kind(blocking_request):
    """Art und HTTP-Status eines Serverfehlers."""
    attribute = _http_status(blocking_request)
    plausible = attribute if attribute is not None and attribute >= 400 \
        else None
    qt_name = _qt_error_name(blocking_request)

    if qt_name in _QT_SERVER_ERRORS:
        if plausible is not None and plausible >= 500:
            return HTTP_SERVER_ERROR, plausible
        return HTTP_SERVER_ERROR, _QT_SERVER_ERRORS[qt_name]

    if qt_name in _QT_CONTENT_ERRORS:
        status = _QT_CONTENT_ERRORS[qt_name]
        if plausible is not None and plausible < 500 \
                and plausible not in _AUTH_STATUS:
            status = plausible
        kind = HTTP_NOT_FOUND if status == 404 else HTTP_REJECTED
        return kind, status

    if plausible is None or plausible in _AUTH_STATUS:
        return None, None
    if plausible >= 500:
        return HTTP_SERVER_ERROR, plausible
    if plausible == 404:
        return HTTP_NOT_FOUND, plausible
    return HTTP_REJECTED, plausible


def _http_error_text(kind, status, host):
    """Serverfehler als Satz, oder None."""
    # Ein translate() je Text für lupdate.
    if kind == HTTP_SERVER_ERROR:
        if status is None:
            return QCoreApplication.translate(
                "GeodiensteLoaderBB",
                "Der Server {host} ist vorübergehend nicht verfügbar. "
                "Später erneut versuchen.",
            ).format(host=host)
        return QCoreApplication.translate(
            "GeodiensteLoaderBB",
            "Der Server {host} ist vorübergehend nicht verfügbar "
            "(Fehler {status}). Später erneut versuchen.",
        ).format(host=host, status=status)

    if kind == HTTP_NOT_FOUND:
        return QCoreApplication.translate(
            "GeodiensteLoaderBB",
            "Der Server {host} kennt die angefragte Adresse nicht "
            "(Fehler 404).",
        ).format(host=host)

    if kind == HTTP_REJECTED:
        if status is None:
            return QCoreApplication.translate(
                "GeodiensteLoaderBB",
                "Der Server {host} hat die Anfrage abgelehnt.",
            ).format(host=host)
        return QCoreApplication.translate(
            "GeodiensteLoaderBB",
            "Der Server {host} hat die Anfrage abgelehnt (Fehler {status}).",
        ).format(host=host, status=status)

    return None


def _network_error_text(blocking_request):
    """Netzwerkfehler als Satz."""
    reply = blocking_request.reply()
    code = reply.error() if reply is not None else None

    def is_error(*names):
        for name in names:
            try:
                if code == enum_value(QNetworkReply, "NetworkError", name):
                    return True
            except AttributeError:
                continue
        return False

    # Ein translate() je Text für lupdate.
    if is_error("HostNotFoundError", "ProxyNotFoundError",
                "ConnectionRefusedError", "UnknownNetworkError"):
        return QCoreApplication.translate(
            "GeodiensteLoaderBB",
            "Keine Verbindung zum Server. Netzwerk und Proxy prüfen "
            "(Einstellungen > Optionen > Netzwerk).",
        )

    if is_error("TimeoutError", "ProxyTimeoutError"):
        return QCoreApplication.translate(
            "GeodiensteLoaderBB",
            "Der Server hat nicht rechtzeitig geantwortet. Später erneut "
            "versuchen.",
        )

    if is_error("ProxyAuthenticationRequiredError",
                "AuthenticationRequiredError"):
        return QCoreApplication.translate(
            "GeodiensteLoaderBB",
            "Die Verbindung verlangt eine Anmeldung. Proxy-Zugangsdaten "
            "unter Einstellungen > Optionen > Netzwerk prüfen.",
        )

    if is_error("SslHandshakeFailedError"):
        return QCoreApplication.translate(
            "GeodiensteLoaderBB",
            "Keine gesicherte Verbindung möglich, meist wegen eines "
            "Zertifikats im Dienstnetz. Bitte an die IT wenden.",
        )

    qt_message = blocking_request.errorMessage()
    return QCoreApplication.translate(
        "GeodiensteLoaderBB", "Abruf fehlgeschlagen: {message}"
    ).format(message=qt_message)


def _evaluate_reply(blocking_request, error_code, url):
    """Prüft das Ergebnis und parst die Antwort."""
    if error_code != enum_value(
        QgsBlockingNetworkRequest, "ErrorCode", "NoError"
    ):
        kind, status = _http_error_kind(blocking_request)
        host = urlsplit(url).hostname or url

        message = (_http_error_text(kind, status, host)
                   or _network_error_text(blocking_request))

        detail = (
            f"{url} (HTTP-Attribut: {_http_status(blocking_request)}, "
            f"Qt: {_qt_error_name(blocking_request) or '-'}): "
            f"{blocking_request.errorMessage()}"
        )
        QgsMessageLog.logMessage(
            f"{message} {detail}", LOG_TAG,
            enum_value(Qgis, "MessageLevel", "Warning"),
        )
        raise ServiceError(message, detail)

    content = bytes(blocking_request.reply().content())
    try:
        return json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Antwort ist kein gültiges JSON: {error}")
