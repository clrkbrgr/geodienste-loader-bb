# -*- coding: utf-8 -*-
# Geodienste-Loader BB - QGIS-Plugin
# Copyright (C) 2026 Landesvermessung und Geobasisinformation Brandenburg
# SPDX-License-Identifier: GPL-3.0-or-later
"""Anbieter und Dienste: Daten, Kategorien, Filter, Ablage."""

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlsplit

from qgis.PyQt.QtCore import QCoreApplication

# ----------------------------------------------------------------------
# Kategorien
# ----------------------------------------------------------------------

# Werte sind Einstellungsschlüssel, nicht übersetzen.
CATEGORY_MUNICIPALITIES = "Ämter und Gemeinden"
CATEGORY_STATE_AUTHORITIES = "Landesbehörden"
CATEGORY_DISTRICTS = "Landkreise"
CATEGORY_OTHERS = "Sonstige"

ALL_CATEGORIES = [
    CATEGORY_MUNICIPALITIES,
    CATEGORY_STATE_AUTHORITIES,
    CATEGORY_DISTRICTS,
    CATEGORY_OTHERS,
]

# Zuordnung wie im Geoportal, über Teilwörter.
_CATEGORY_WORDS = (
    (CATEGORY_MUNICIPALITIES,
     ("Amt", "Gemeinde", "Stadt", "Verbandsgemeinde", "Ortsgemeinde")),
    (CATEGORY_STATE_AUTHORITIES,
     ("Einrichtung des Landes", "Landesamt", "Landesbetrieb",
      "Ministerium")),
    (CATEGORY_DISTRICTS, ("Landkreis",)),
)


def category_label(category):
    """Übersetzte Anzeige einer Kategorie."""
    # Ein translate() je Text für lupdate.
    labels = {
        CATEGORY_MUNICIPALITIES: QCoreApplication.translate(
            "GeodiensteLoaderBB", "Ämter und Gemeinden"
        ),
        CATEGORY_STATE_AUTHORITIES: QCoreApplication.translate(
            "GeodiensteLoaderBB", "Landesbehörden"
        ),
        CATEGORY_DISTRICTS: QCoreApplication.translate(
            "GeodiensteLoaderBB", "Landkreise"
        ),
        CATEGORY_OTHERS: QCoreApplication.translate(
            "GeodiensteLoaderBB", "Sonstige"
        ),
    }
    return labels.get(category, category)


def get_category(function):
    """Kategorie zur Anbieterart, sonst "Sonstige"."""
    function = (function or "").strip()
    for category, words in _CATEGORY_WORDS:
        if any(word in function for word in words):
            return category
    return CATEGORY_OTHERS


# ----------------------------------------------------------------------
# Namen
# ----------------------------------------------------------------------

# Rechtsform der Search API -> Art im Geoportal
LEGAL_FORM_FUNCTIONS = {
    "Gemeinde": "Amtsfreie Gemeinde",
    "Amt": "Amt",
    "Kreisfreie Stadt": "Kreisfreie Stadt",
}

# "LfU" ist eine Abkürzung, "Oder" nicht.
_ABBREVIATION_UPPERCASE_RATIO = 0.5

_ABBREVIATION_MAX_LENGTH = 12


def split_legal_form(name):
    """Trennt die Rechtsform ab: "Beelitz (Gemeinde)" -> "Beelitz"."""
    match = re.search(r"^(.*\S)\s*\(([^()]+)\)\s*$", name)
    if match and match.group(2) in LEGAL_FORM_FUNCTIONS:
        return match.group(1), LEGAL_FORM_FUNCTIONS[match.group(2)]
    return name, None


def build_display_name(name):
    """Stellt eine Abkürzung nach vorn: "LfU - Landesamt für Umwelt"."""
    match = re.search(r"^(.*?)\s*\(([^()]+)\)\s*$", name)
    if not match:
        return name

    base, parenthetical = match.group(1).strip(), match.group(2).strip()
    if not base or len(parenthetical) > _ABBREVIATION_MAX_LENGTH:
        return name

    letters = [c for c in parenthetical if c.isalpha()]
    if not letters:
        return name

    uppercase_share = sum(1 for c in letters if c.isupper()) / len(letters)
    if uppercase_share < _ABBREVIATION_UPPERCASE_RATIO:
        return name

    return f"{parenthetical} - {base}"


def provider_display_name(name):
    """Anbietername wie im Reiter "Diensteanbieter"."""
    return build_display_name(split_legal_form((name or "").strip())[0])


# ----------------------------------------------------------------------
# Datenklassen
# ----------------------------------------------------------------------

SUPPORTED_SCHEMA_VERSION = 4


@dataclass
class Provider:
    """Ein Diensteanbieter."""
    key: str
    name: str
    display_name: str
    function: str
    category: str
    service_count: int


def make_provider(key, name, function, service_count):
    """Provider mit Anzeigename und Kategorie."""
    return Provider(
        key=key,
        name=name,
        display_name=build_display_name(name),
        function=function or "",
        category=get_category(function),
        service_count=int(service_count or 0),
    )


@dataclass
class Service:
    """Ein Geodienst."""
    id: str
    title: str
    description: str
    type: str
    url: str
    metadata_url: str
    provider: str
    flags: frozenset = frozenset()
    # (min_lon, min_lat, max_lon, max_lat), EPSG:4326
    bbox: Optional[tuple] = None


_NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def bbox_from_wkt(wkt):
    """Umgebendes Rechteck einer WKT-Geometrie, oder None."""
    numbers = [float(n) for n in _NUMBER.findall(wkt or "")]
    if len(numbers) < 4 or len(numbers) % 2:
        return None
    lons, lats = numbers[0::2], numbers[1::2]
    return (min(lons), min(lats), max(lons), max(lats))


_WEB_SCHEMES = {"https", "http"}


def web_url_or_empty(url):
    """Nur https- oder http-Adressen, sonst ""."""
    if not isinstance(url, str):
        return ""
    url = url.strip()
    if urlsplit(url).scheme.lower() not in _WEB_SCHEMES:
        return ""
    return url


def _text(value):
    """Wert als Text, "" auch für null."""
    if value is None:
        return ""
    return str(value)


def services_from_api(raw_services):
    """Service-Objekte aus Treffern einer Schnittstelle."""
    return [
        Service(
            id=_text(raw.get("id")),
            title=_text(raw.get("title")),
            description=_text(raw.get("description")),
            type=_text(raw.get("service_type")) or "UNKNOWN",
            url=_text(raw.get("service_url")),
            metadata_url=web_url_or_empty(raw.get("metadata_url")),
            provider=provider_display_name(raw.get("provider")),
            flags=frozenset(raw.get("flags", ())),
            bbox=bbox_from_wkt(raw.get("geometry", "")),
        )
        for raw in raw_services
    ]


# ----------------------------------------------------------------------
# Filter
# ----------------------------------------------------------------------

def normalize(text):
    """Text für den Vergleich."""
    text = text.lower().replace("-", " ")
    for umlaut, replacement in (
        ("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"),
    ):
        text = text.replace(umlaut, replacement)
    return text


def filter_providers(providers, name_filter, active_categories):
    """Anbieter nach Namensteil und Kategorie."""
    needle = normalize(name_filter.strip())

    result = []
    for provider in providers:
        if provider.category not in active_categories:
            continue
        haystack = normalize(provider.name + " " + provider.display_name)
        if needle and needle not in haystack:
            continue
        result.append(provider)

    return result


def filter_services(services, query="", service_types=None, flags=None):
    """Dienste lokal filtern."""
    words = normalize(query.strip()).split()
    types = set(service_types or ())
    required_flags = set(flags or ())

    result = []
    for service in services:
        if types and service.type not in types:
            continue
        if not required_flags <= service.flags:
            continue
        if words:
            haystack = normalize(service.title + " " + service.description)
            if not all(word in haystack for word in words):
                continue
        result.append(service)

    return result


# ----------------------------------------------------------------------
# Ablage als Datei
# ----------------------------------------------------------------------

class SchemaVersionError(ValueError):
    """Anbieterdatei mit anderer Schemaversion."""

    def __init__(self, found, message):
        super().__init__(message)
        self.found = found

    def is_older(self):
        """True bei Datei aus älterer Plugin-Version."""
        return (isinstance(self.found, int)
                and self.found < SUPPORTED_SCHEMA_VERSION)


class ProviderList:
    """Anbieterliste mit Stand und Herkunftsdatei."""

    def __init__(self, providers, generated, path):
        self.providers = providers
        self.generated = generated
        self.path = path


def providers_from_file(data):
    """Provider-Objekte aus einer Anbieterdatei."""
    version = data.get("schema_version")
    if version != SUPPORTED_SCHEMA_VERSION:
        raise SchemaVersionError(
            version,
            f"Liste der Diensteanbieter hat Schema {version}, "
            f"erwartet wird {SUPPORTED_SCHEMA_VERSION}."
        )

    providers = []
    for entry in data.get("providers", []):
        key = (entry.get("key") or "").strip()
        name = (entry.get("name") or "").strip()
        if not key or not name:
            continue
        providers.append(make_provider(
            key, name, entry.get("function", ""),
            entry.get("service_count", 0),
        ))

    return sort_providers(providers)


def sort_providers(providers):
    """Nach Anzeigename sortiert."""
    return sorted(providers, key=lambda p: p.display_name.casefold())


def build_provider_file(providers, generated, source):
    """Inhalt einer Anbieterdatei."""
    entries = [
        {
            "key": provider.key,
            "name": provider.name,
            "function": provider.function,
            "service_count": provider.service_count,
        }
        for provider in providers
        if provider.key and provider.name.strip()
    ]
    entries.sort(key=lambda e: e["key"])

    return {
        "schema_version": SUPPORTED_SCHEMA_VERSION,
        "generated": generated,
        "source": source,
        "provider_count": len(entries),
        "service_count": sum(e["service_count"] for e in entries),
        "providers": entries,
    }


def parse_generated(value):
    """Zeitstempel als datetime in UTC, oder None."""
    if not value:
        return None
    try:
        # fromisoformat() kennt "Z" erst ab Python 3.11.
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def read_provider_list(path):
    """Liest eine Anbieterdatei."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return ProviderList(
        providers_from_file(data),
        parse_generated(data.get("generated")),
        path,
    )


def user_path(profile_dir, filename):
    """Pfad der Anbieterliste im QGIS-Profil."""
    return os.path.join(profile_dir, "geodienste_loader_bb", filename)


def load_newest(bundled_path, user_path):
    """
    Die jüngere von mitgelieferter Liste und Profil-Kopie.

    :return: (ProviderList, Warnung oder None)
    """
    bundled = read_provider_list(bundled_path)

    if not os.path.exists(user_path):
        return bundled, None

    try:
        user = read_provider_list(user_path)
    except SchemaVersionError as error:
        if not error.is_older():
            return bundled, (
                f"Die gespeicherte Liste der Diensteanbieter {user_path} "
                f"ist unbrauchbar und wird übergangen: {error}"
            )
        try:
            os.remove(user_path)
        except OSError as remove_error:
            return bundled, (
                f"Die veraltete Liste der Diensteanbieter {user_path} "
                f"(Schema {error.found}) ließ sich nicht löschen: "
                f"{remove_error}"
            )
        return bundled, (
            f"Veraltete Liste der Diensteanbieter {user_path} "
            f"(Schema {error.found}) aus einer früheren Plugin-Version "
            f"gelöscht."
        )
    except (OSError, ValueError) as error:
        return bundled, (
            f"Die gespeicherte Liste der Diensteanbieter {user_path} "
            f"ist unbrauchbar und wird übergangen: {error}"
        )

    user_stamp = user.generated or datetime.min.replace(tzinfo=timezone.utc)
    bundled_stamp = (bundled.generated
                     or datetime.min.replace(tzinfo=timezone.utc))
    if user_stamp > bundled_stamp:
        return user, None
    return bundled, None


def write_provider_file(path, data):
    """Schreibt über eine temporäre Datei."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def now_iso():
    """Jetzt in UTC als ISO 8601 mit "Z"."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
