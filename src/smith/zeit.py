"""Öffnungszeiten rechnen: Ist offen? Wann wieder? Wie klingt das am Telefon?"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from zoneinfo import ZoneInfo

import holidays

from .profil import WOCHENTAGE, Profil

WOCHENTAG_ANZEIGE = (
    "Montag",
    "Dienstag",
    "Mittwoch",
    "Donnerstag",
    "Freitag",
    "Samstag",
    "Sonntag",
)


def jetzt(profil: Profil) -> dt.datetime:
    return dt.datetime.now(ZoneInfo(profil.assistent.zeitzone))


def _spanne(text: str) -> tuple[dt.time, dt.time]:
    von, bis = text.split("-")
    return dt.time.fromisoformat(von), dt.time.fromisoformat(bis)


def sonderzeit_fuer(profil: Profil, datum: dt.date):
    for sonder in profil.sonderzeiten:
        if sonder.von <= datum <= sonder.ende:
            return sonder
    return None


@lru_cache(maxsize=64)
def _feiertage(bundesland: str, jahr: int) -> dict[dt.date, str]:
    return dict(
        holidays.country_holidays(
            "DE", subdiv=bundesland or None, years=jahr, language="de"
        )
    )


def feiertag(profil: Profil, datum: dt.date) -> str | None:
    """Name des gesetzlichen Feiertags am Datum (im Bundesland des Betriebs) oder None."""
    return _feiertage(profil.bundesland, datum.year).get(datum)


def zeiten_am(profil: Profil, datum: dt.date) -> list[tuple[dt.time, dt.time]]:
    """Öffnungszeiten an einem Datum. Vorrang: Sonderzeiten, dann Feiertage, dann Wochenplan."""
    sonder = sonderzeit_fuer(profil, datum)
    if sonder is not None:
        texte = sonder.zeiten
    elif profil.feiertage_geschlossen and feiertag(profil, datum):
        texte = []
    else:
        texte = profil.oeffnungszeiten.get(WOCHENTAGE[datum.weekday()], [])
    return [_spanne(t) for t in texte]


def geschlossen_grund(profil: Profil, datum: dt.date) -> str:
    """Hinweis, warum an einem Datum abweichend geschlossen ist – für Ansagen."""
    sonder = sonderzeit_fuer(profil, datum)
    if sonder is not None:
        return sonder.hinweis
    if profil.feiertage_geschlossen and (name := feiertag(profil, datum)):
        return f"Feiertag: {name}"
    return ""


def ist_offen(profil: Profil, zeitpunkt: dt.datetime) -> bool:
    uhrzeit = zeitpunkt.time()
    return any(von <= uhrzeit < bis for von, bis in zeiten_am(profil, zeitpunkt.date()))


def naechste_oeffnung(
    profil: Profil, zeitpunkt: dt.datetime, max_tage: int = 60
) -> dt.datetime | None:
    for offset in range(max_tage + 1):
        datum = zeitpunkt.date() + dt.timedelta(days=offset)
        for von, _bis in zeiten_am(profil, datum):
            beginn = dt.datetime.combine(datum, von, tzinfo=zeitpunkt.tzinfo)
            if beginn > zeitpunkt:
                return beginn
    return None


def uhrzeit_sprechen(zeit: dt.time) -> str:
    """09:30 -> '9 Uhr 30', 14:00 -> '14 Uhr' – so liest die Sprachausgabe es sauber vor."""
    if zeit.minute == 0:
        return f"{zeit.hour} Uhr"
    return f"{zeit.hour} Uhr {zeit.minute:02d}"


def datum_sprechen(datum: dt.date, heute: dt.date | None = None) -> str:
    if heute is not None:
        if datum == heute:
            return "heute"
        if datum == heute + dt.timedelta(days=1):
            return "morgen"
    return f"{WOCHENTAG_ANZEIGE[datum.weekday()]}, den {datum.day}.{datum.month}."


def zeiten_text(spannen: list[tuple[dt.time, dt.time]]) -> str:
    if not spannen:
        return "geschlossen"
    return " und ".join(
        f"{uhrzeit_sprechen(von)} bis {uhrzeit_sprechen(bis)}" for von, bis in spannen
    )


def wochenplan_text(profil: Profil) -> str:
    """Kompakte Übersicht für den Systemprompt; gleiche Tage werden zusammengefasst."""
    zeilen: list[str] = []
    gruppe_start = 0
    for i in range(1, len(WOCHENTAGE) + 1):
        ende_der_gruppe = i == len(WOCHENTAGE) or (
            profil.oeffnungszeiten[WOCHENTAGE[i]]
            != profil.oeffnungszeiten[WOCHENTAGE[gruppe_start]]
        )
        if ende_der_gruppe:
            spannen = [
                _spanne(t) for t in profil.oeffnungszeiten[WOCHENTAGE[gruppe_start]]
            ]
            tage = WOCHENTAG_ANZEIGE[gruppe_start]
            if i - 1 == gruppe_start + 1:
                tage += f" und {WOCHENTAG_ANZEIGE[i - 1]}"
            elif i - 1 > gruppe_start:
                tage += f" bis {WOCHENTAG_ANZEIGE[i - 1]}"
            zeilen.append(f"{tage}: {zeiten_text(spannen)}")
            gruppe_start = i
    return "\n".join(zeilen)


def status_text(profil: Profil, zeitpunkt: dt.datetime) -> str:
    """Ein Satz, der den aktuellen Stand beschreibt – für Prompt und Tools."""
    if ist_offen(profil, zeitpunkt):
        for von, bis in zeiten_am(profil, zeitpunkt.date()):
            if von <= zeitpunkt.time() < bis:
                return f"Der Betrieb ist gerade geöffnet, heute noch bis {uhrzeit_sprechen(bis)}."
    naechste = naechste_oeffnung(profil, zeitpunkt)
    grund = geschlossen_grund(profil, zeitpunkt.date())
    hinweis = f" ({grund})" if grund else ""
    if naechste is None:
        return f"Der Betrieb ist gerade geschlossen{hinweis}."
    return (
        f"Der Betrieb ist gerade geschlossen{hinweis}. Nächste Öffnung: "
        f"{datum_sprechen(naechste.date(), zeitpunkt.date())} um {uhrzeit_sprechen(naechste.time())}."
    )
