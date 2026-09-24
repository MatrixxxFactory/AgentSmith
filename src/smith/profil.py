"""Branchenprofile: alles, was einen Betrieb ausmacht, steht in einer YAML-Datei.

Der Code kennt keine Branche. Friseur, Handwerker oder Praxis unterscheiden sich
nur durch ihr Profil unter ``profile/``. Neue Zielgruppe = neue YAML-Datei.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PROJEKT_ROOT = Path(__file__).resolve().parents[2]
PROFIL_ORDNER = PROJEKT_ROOT / "profile"

WOCHENTAGE = (
    "montag",
    "dienstag",
    "mittwoch",
    "donnerstag",
    "freitag",
    "samstag",
    "sonntag",
)

BUNDESLAENDER = (
    "BB",
    "BE",
    "BW",
    "BY",
    "HB",
    "HE",
    "HH",
    "MV",
    "NI",
    "NW",
    "RP",
    "SH",
    "SL",
    "SN",
    "ST",
    "TH",
)

_ZEITSPANNE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)$")


class _Streng(BaseModel):
    """Tippfehler im YAML sollen auffallen, statt still ignoriert zu werden."""

    model_config = ConfigDict(extra="forbid")


def _zeitspannen_pruefen(werte: list[str]) -> list[str]:
    for wert in werte:
        treffer = _ZEITSPANNE.match(wert)
        if not treffer:
            raise ValueError(f"Zeitspanne '{wert}' muss das Format HH:MM-HH:MM haben")
        von = int(treffer[1]) * 60 + int(treffer[2])
        bis = int(treffer[3]) * 60 + int(treffer[4])
        if bis <= von:
            raise ValueError(f"Zeitspanne '{wert}' endet vor ihrem Beginn")
    return werte


class Firma(_Streng):
    name: str
    branche: str
    beschreibung: str = ""
    adresse: str = ""
    telefon: str = ""
    email: str = ""
    webseite: str = ""


class Assistent(_Streng):
    name: str = "Smith"
    begruessung: str
    tonfall: str = "freundlich, professionell, per Sie"
    sprache: str = "de"
    zeitzone: str = "Europe/Berlin"


class Sonderzeit(_Streng):
    """Abweichende Öffnungszeiten, z. B. Feiertage oder Betriebsurlaub."""

    von: dt.date
    bis: dt.date | None = None
    zeiten: list[str] = Field(default_factory=list)  # leer = geschlossen
    hinweis: str = ""

    _pruefe_zeiten = field_validator("zeiten")(_zeitspannen_pruefen)

    @property
    def ende(self) -> dt.date:
        return self.bis or self.von


class Leistung(_Streng):
    name: str
    dauer_min: int = Field(default=30, gt=0)
    preis: str = ""
    beschreibung: str = ""


class FAQ(_Streng):
    frage: str
    antwort: str


class TermineModul(_Streng):
    aktiv: bool = False
    raster_min: int = Field(default=30, gt=0)  # Takt, in dem Termine beginnen
    parallel: int = Field(default=1, gt=0)  # gleichzeitige Termine (Stühle, Monteure …)
    vorlauf_stunden: int = Field(default=2, ge=0)  # frühester Termin ab jetzt
    max_tage_voraus: int = Field(default=30, gt=0)


class RueckrufModul(_Streng):
    aktiv: bool = True


class WeiterleitungModul(_Streng):
    aktiv: bool = False
    nummer: str = ""  # E.164, z. B. +4930123456
    nur_waehrend_oeffnungszeiten: bool = True
    anlaesse: list[str] = Field(default_factory=list)  # wann weiterleiten

    @model_validator(mode="after")
    def _nummer_noetig(self) -> WeiterleitungModul:
        if self.aktiv and not self.nummer:
            raise ValueError("Weiterleitung ist aktiv, aber es fehlt 'nummer'")
        return self


class Module(_Streng):
    termine: TermineModul = Field(default_factory=TermineModul)
    rueckruf: RueckrufModul = Field(default_factory=RueckrufModul)
    weiterleitung: WeiterleitungModul = Field(default_factory=WeiterleitungModul)


class Kalender(_Streng):
    # "datei": Termine in daten/<profil>/termine.json (zum Testen)
    # "google": Google Calendar – Kalender-ID und Dienstkonto stehen in .env.local
    #           (SMITH_GOOGLE_KALENDER_ID, SMITH_GOOGLE_DIENSTKONTO)
    art: Literal["datei", "google"] = "datei"


class Benachrichtigung(_Streng):
    # Jede neue Buchung / Rückrufbitte geht als JSON an diese URL
    # (z. B. n8n, Make oder Zapier, die daraus E-Mail oder WhatsApp machen).
    webhook_url: str = ""


# Ausgewählte deutsche Stimmen: Name -> (TTS-Modell, Stimmen-ID).
# Gradium-Stimmen sind offizielle Kundenservice-Stimmen und starten am Telefon
# deutlich schneller als die Fish-Audio-Stimme der Vorlage (~0,5 s statt ~1,3 s).
SPRECHER: dict[str, tuple[str, str]] = {
    # weiblich, aufmerksam, effizient
    "annika": ("gradium/default", "p6Uutkyi3j2iNAUu"),
    # männlich, aufmerksam, auf den Punkt
    "mats": ("gradium/default", "Kf5m22mROozoMWj3"),
}


class Stimme(_Streng):
    stt: str = "assemblyai/universal-3-5-pro"
    llm: str = "google/gemma-4-31b-it"
    # Einfach einen Namen aus SPRECHER wählen …
    sprecher: str = "annika"
    # … oder Modell und Stimmen-ID direkt angeben (hat Vorrang vor sprecher)
    tts: str = ""
    voice: str = ""
    # Emotions-Markup; nur Stimmen mit Markup-Unterstützung (z. B. Fish Audio) nutzen es
    expressive: bool = False

    @model_validator(mode="after")
    def _sprecher_aufloesen(self) -> Stimme:
        if self.tts and self.voice:
            return self
        if self.tts or self.voice:
            raise ValueError(
                "tts und voice nur zusammen angeben – oder stattdessen 'sprecher'"
            )
        name = self.sprecher.strip().lower()
        if name not in SPRECHER:
            raise ValueError(
                f"Unbekannter Sprecher '{self.sprecher}'. Verfügbar: {', '.join(SPRECHER)}"
            )
        self.tts, self.voice = SPRECHER[name]
        return self


class Profil(_Streng):
    id: str = ""  # wird aus dem Dateinamen gesetzt
    firma: Firma
    assistent: Assistent
    oeffnungszeiten: dict[str, list[str]]
    sonderzeiten: list[Sonderzeit] = Field(default_factory=list)
    # Gesetzliche Feiertage gelten automatisch als geschlossen (Sonderzeiten haben
    # Vorrang). Bundesland als Kürzel, z. B. BE, BY, NW; leer = nur bundesweite.
    bundesland: str = ""
    feiertage_geschlossen: bool = True
    leistungen: list[Leistung] = Field(default_factory=list)
    faq: list[FAQ] = Field(default_factory=list)
    regeln: list[str] = Field(default_factory=list)
    notfall: str = ""
    module: Module = Field(default_factory=Module)
    kalender: Kalender = Field(default_factory=Kalender)
    benachrichtigung: Benachrichtigung = Field(default_factory=Benachrichtigung)
    stimme: Stimme = Field(default_factory=Stimme)
    telefonnummern: list[str] = Field(default_factory=list)
    schluesselwoerter: list[str] = Field(default_factory=list)

    @field_validator("oeffnungszeiten", mode="before")
    @classmethod
    def _oeffnungszeiten_normalisieren(cls, wert: object) -> dict[str, list[str]]:
        if not isinstance(wert, dict):
            raise ValueError(
                "oeffnungszeiten muss eine Zuordnung Wochentag -> Zeiten sein"
            )
        ergebnis: dict[str, list[str]] = {tag: [] for tag in WOCHENTAGE}
        for tag, zeiten in wert.items():
            tag = str(tag).lower()
            if tag not in WOCHENTAGE:
                raise ValueError(f"Unbekannter Wochentag '{tag}'")
            if zeiten in (None, "geschlossen", False):
                zeiten = []
            elif isinstance(zeiten, str):
                zeiten = [z.strip() for z in zeiten.split(",")]
            ergebnis[tag] = _zeitspannen_pruefen(list(zeiten))
        return ergebnis

    @field_validator("bundesland")
    @classmethod
    def _bundesland_pruefen(cls, wert: str) -> str:
        wert = wert.strip().upper()
        if wert and wert not in BUNDESLAENDER:
            raise ValueError(
                f"Unbekanntes Bundesland '{wert}'. Erlaubt: {', '.join(BUNDESLAENDER)}"
            )
        return wert

    def leistung_finden(self, name: str) -> Leistung | None:
        gesucht = name.strip().lower()
        for leistung in self.leistungen:
            if leistung.name.lower() == gesucht:
                return leistung
        for leistung in self.leistungen:
            if gesucht in leistung.name.lower() or leistung.name.lower() in gesucht:
                return leistung
        return None

    @property
    def stt_schluesselwoerter(self) -> list[str]:
        woerter = [self.firma.name, self.assistent.name, *self.schluesselwoerter]
        woerter += [leistung.name for leistung in self.leistungen]
        return list(dict.fromkeys(w for w in woerter if w))


def profil_laden(pfad: Path | str) -> Profil:
    pfad = Path(pfad)
    daten = yaml.safe_load(pfad.read_text(encoding="utf-8")) or {}
    daten.setdefault("id", pfad.stem)
    return Profil.model_validate(daten)


def alle_profile(ordner: Path = PROFIL_ORDNER) -> list[Profil]:
    # Dateien mit "_" am Anfang sind Vorlagen und werden nie ausgewählt
    return [
        profil_laden(pfad)
        for pfad in sorted(ordner.glob("*.yaml"))
        if not pfad.name.startswith("_")
    ]


def _nummer_normalisieren(nummer: str) -> str:
    ziffern = re.sub(r"[^\d+]", "", nummer)
    if ziffern.startswith("00"):
        ziffern = "+" + ziffern[2:]
    return ziffern


def profil_waehlen(
    angerufene_nummer: str | None = None,
    standard: str | None = None,
    ordner: Path = PROFIL_ORDNER,
) -> Profil:
    """Findet das Profil zur angerufenen Nummer, sonst das Standardprofil.

    So kann ein einziger Agent mehrere Betriebe bedienen: jede Telefonnummer
    zeigt auf ein anderes Profil.
    """
    profile = alle_profile(ordner)
    if not profile:
        raise FileNotFoundError(f"Keine Profile in {ordner} gefunden")

    if angerufene_nummer:
        gesucht = _nummer_normalisieren(angerufene_nummer)
        for profil in profile:
            if gesucht in {_nummer_normalisieren(n) for n in profil.telefonnummern}:
                return profil

    standard = standard or os.getenv("SMITH_PROFIL")
    if standard:
        for profil in profile:
            if profil.id == standard:
                return profil
        raise FileNotFoundError(f"Profil '{standard}' nicht in {ordner} gefunden")
    return profile[0]


Tageszeit = Literal["egal", "vormittag", "nachmittag", "abend"]
