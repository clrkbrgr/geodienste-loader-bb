# Geodienste-Loader BB

QGIS-Plugin der LGB (Landesvermessung und Geobasisinformation Brandenburg).
Es zeigt die Diensteanbieter und Geodienste des Geoportals Brandenburg
direkt in QGIS und lädt die Dienste als Layer.

*English: QGIS plugin to find geodata providers and geo web services of the
Brandenburg spatial data infrastructure (GDI-BB, Germany) and load them as
layers. The user interface is available in German and English.*

## Funktionen

- **Diensteanbieter**: alle Anbieter des Geoportals mit Art und Anzahl der
  Dienste, filterbar nach Ämter und Gemeinden, Landesbehörden, Landkreise
  und Sonstige.
- **Dienste**: die Dienste eines Anbieters oder des gesamten Katalogs,
  filterbar nach Diensteart (WMS, WMTS, WFS, WCS, OGC API) sowie nach
  Open Data, INSPIRE und Landesweit, mit Suche über Titel und
  Beschreibung.
- **Laden**: Dienste werden über den Quelldialog von QGIS geladen.
- **Weitere Aktionen**: Dienst-URL kopieren, Metadaten im Geoportal
  öffnen, auf die Ausdehnung des Dienstes zoomen.

## Voraussetzungen

- QGIS 3.44 (LTR) oder QGIS 4.x
- Keine zusätzlichen Python-Pakete

## Installation

**Über QGIS:** Erweiterungen > Erweiterungen verwalten und installieren >
nach „Geodienste-Loader BB“ suchen > Installieren.

**Aus einer Zip-Datei:** Erweiterungen > Erweiterungen verwalten und
installieren > Aus ZIP installieren.

Nach der Installation öffnet das Symbol in der Werkzeugleiste oder der
Eintrag unter Web > Geodienste-Loader BB das Bedienfeld.

## Bedienung

1. Im Reiter **Diensteanbieter** einen Anbieter suchen oder über die
   Kategorien eingrenzen, dann doppelklicken oder **Dienste anzeigen**.
2. Im Reiter **Dienste** stehen seine Dienste. **Gesamter Katalog** zeigt
   stattdessen alle Dienste des Geoportals. Das Suchfeld durchsucht Titel
   und Beschreibung.
3. Mit den Filterknöpfen nach Diensteart, Open Data, INSPIRE oder
   Landesweit eingrenzen.
4. Einen Dienst doppelklicken oder **Layer laden**. Es öffnet sich der
   Quelldialog von QGIS, dort die gewünschten Layer hinzufügen.

**URL**, **Metadaten** und **Zoom** unter der Tabelle (auch per
Rechtsklick) kopieren die Dienst-URL, öffnen die Metadaten im Geoportal
oder zoomen auf die Ausdehnung des Dienstes.

**Gut zu wissen:** Das Plugin legt beim Laden nur vorübergehend eine
Verbindung in QGIS an und entfernt sie danach wieder. Wer einen Dienst
dauerhaft in der Datenquellenverwaltung speichern möchte, kopiert mit **URL**
die Adresse und legt die Verbindung in QGIS über „Neu“ selbst an.


## Fehler melden

Bitte über die [Issues](https://github.com/clrkbrgr/geodienste-loader-bb/issues)
dieses Repositorys. Hilfreich sind QGIS-Version, Betriebssystem und die
Meldungen im Bedienfeld Protokollnachrichten, Reiter
„Geodienste-Loader BB“.

