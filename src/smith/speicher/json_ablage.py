"""Einfachster Speicher: JSON-Dateien unter ``daten/<profil-id>/``.

Reicht für Tests und für kleine Betriebe mit einem Agenten. Für mehrere
gleichzeitige Agent-Prozesse einen echten Kalender/eine Datenbank anschließen.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from . import Nachricht, Termin


def _nur_ziffern(telefon: str) -> str:
    ziffern = re.sub(r"\D", "", telefon)
    # +49 151… und 0151… sollen als dieselbe Nummer gelten
    if ziffern.startswith("49"):
        ziffern = ziffern[2:]
    return ziffern.lstrip("0")


class JsonAblage:
    def __init__(self, ordner: Path) -> None:
        self._ordner = ordner
        self._ordner.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    # --- Hilfen -----------------------------------------------------------

    def _lesen(self, datei: str) -> list[dict[str, Any]]:
        pfad = self._ordner / datei
        if not pfad.exists():
            return []
        return json.loads(pfad.read_text(encoding="utf-8"))

    def _schreiben(self, datei: str, eintraege: list[dict[str, Any]]) -> None:
        pfad = self._ordner / datei
        tmp = pfad.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(eintraege, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(pfad)

    def _termine(self) -> list[Termin]:
        return [Termin.aus_dict(d) for d in self._lesen("termine.json")]

    # --- Kalender ---------------------------------------------------------

    async def termine_zwischen(
        self, von: dt.datetime, bis: dt.datetime
    ) -> list[Termin]:
        return [
            t
            for t in self._termine()
            if t.status == "gebucht" and t.beginn < bis and t.ende > von
        ]

    async def buchen(self, termin: Termin) -> Termin:
        async with self._lock:
            eintraege = self._lesen("termine.json")
            eintraege.append(termin.als_dict())
            self._schreiben("termine.json", eintraege)
        return termin

    async def termine_von(self, telefon: str, ab: dt.datetime) -> list[Termin]:
        gesucht = _nur_ziffern(telefon)
        if not gesucht:
            return []
        return sorted(
            (
                t
                for t in self._termine()
                if t.status == "gebucht"
                and t.beginn >= ab
                and _nur_ziffern(t.telefon) == gesucht
            ),
            key=lambda t: t.beginn,
        )

    async def absagen(self, termin_id: str) -> Termin | None:
        async with self._lock:
            eintraege = self._lesen("termine.json")
            for eintrag in eintraege:
                if eintrag["id"] == termin_id and eintrag["status"] == "gebucht":
                    eintrag["status"] = "abgesagt"
                    self._schreiben("termine.json", eintraege)
                    return Termin.aus_dict(eintrag)
        return None

    # --- Postfach ---------------------------------------------------------

    async def ablegen(self, nachricht: Nachricht) -> Nachricht:
        async with self._lock:
            eintraege = self._lesen("nachrichten.json")
            eintraege.append(nachricht.als_dict())
            self._schreiben("nachrichten.json", eintraege)
        return nachricht

    # --- Anrufprotokoll ---------------------------------------------------

    async def anruf_speichern(self, daten: dict[str, Any]) -> None:
        ordner = self._ordner / "anrufe"
        ordner.mkdir(exist_ok=True)
        zeitstempel = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        pfad = ordner / f"{zeitstempel}.json"
        pfad.write_text(
            json.dumps(daten, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
