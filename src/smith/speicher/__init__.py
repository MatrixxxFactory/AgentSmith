"""Speicher-Schnittstellen.

Die Module reden nur mit diesen Protokollen. Dahinter steckt eine JSON-Datei
(json_ablage.py) oder Google Calendar (google_kalender.py); weitere wie Cal.com
oder eine Praxissoftware lassen sich anschließen, ohne ein Modul anzufassen.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


def _neue_id() -> str:
    return uuid.uuid4().hex[:8]


def telefon_normalisieren(telefon: str) -> str:
    """Nur Ziffern ohne Landes-/Ortsvorwahl-Null: +49 151… und 0151… sind gleich."""
    ziffern = re.sub(r"\D", "", telefon)
    if ziffern.startswith("0049"):
        ziffern = ziffern[4:]
    elif ziffern.startswith("49"):
        ziffern = ziffern[2:]
    return ziffern.lstrip("0")


@dataclass
class Termin:
    leistung: str
    beginn: dt.datetime
    ende: dt.datetime
    name: str
    telefon: str
    notiz: str = ""
    id: str = field(default_factory=_neue_id)
    status: str = "gebucht"  # oder "abgesagt"
    # Blockiert alle parallelen Plätze, z. B. ganztägiger Urlaub im Kalender
    exklusiv: bool = False
    erstellt: dt.datetime = field(
        default_factory=lambda: dt.datetime.now(dt.timezone.utc)
    )

    def als_dict(self) -> dict[str, Any]:
        daten = asdict(self)
        for schluessel in ("beginn", "ende", "erstellt"):
            daten[schluessel] = daten[schluessel].isoformat()
        return daten

    @classmethod
    def aus_dict(cls, daten: dict[str, Any]) -> Termin:
        daten = dict(daten)
        for schluessel in ("beginn", "ende", "erstellt"):
            daten[schluessel] = dt.datetime.fromisoformat(daten[schluessel])
        return cls(**daten)


@dataclass
class Nachricht:
    art: str  # "rueckruf" oder "hinweis"
    name: str
    telefon: str
    anliegen: str
    dringend: bool = False
    id: str = field(default_factory=_neue_id)
    erstellt: dt.datetime = field(
        default_factory=lambda: dt.datetime.now(dt.timezone.utc)
    )

    def als_dict(self) -> dict[str, Any]:
        daten = asdict(self)
        daten["erstellt"] = self.erstellt.isoformat()
        return daten


class Kalender(Protocol):
    async def termine_zwischen(
        self, von: dt.datetime, bis: dt.datetime
    ) -> list[Termin]:
        """Alle gebuchten (nicht abgesagten) Termine, die den Zeitraum berühren."""
        ...

    async def buchen(self, termin: Termin) -> Termin: ...

    async def termine_von(self, telefon: str, ab: dt.datetime) -> list[Termin]: ...

    async def absagen(self, termin_id: str) -> Termin | None: ...


class Postfach(Protocol):
    async def ablegen(self, nachricht: Nachricht) -> Nachricht: ...


class Anrufprotokoll(Protocol):
    async def anruf_speichern(self, daten: dict[str, Any]) -> None: ...
