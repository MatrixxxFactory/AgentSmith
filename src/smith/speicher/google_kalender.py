"""Termine direkt im Google Calendar des Betriebs.

- Gebuchte Termine erscheinen als normale Kalendereinträge ("Damenhaarschnitt – Julia Neumann").
- Einträge, die der Betrieb selbst anlegt, blockieren Zeiten automatisch. Ganztägige
  Einträge (Urlaub, Fortbildung) blockieren den ganzen Tag; Einträge mit "Verfügbarkeit:
  frei" werden ignoriert.
- Name, Telefon usw. liegen zusätzlich in privaten Event-Eigenschaften, damit der Agent
  Termine eines Anrufers wiederfindet.

Zugang über ein Google-Dienstkonto (Anleitung: README, Abschnitt "Google Calendar").
Der Kalender muss für die E-Mail-Adresse des Dienstkontos freigegeben sein
("Änderungen an Terminen vornehmen").

API-Doku: https://developers.google.com/workspace/calendar/api/v3/reference/events
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import aiohttp

from . import Termin, telefon_normalisieren

logger = logging.getLogger("smith.google_kalender")

API = "https://www.googleapis.com/calendar/v3"
SCOPE = "https://www.googleapis.com/auth/calendar.events"

TokenQuelle = Callable[[], Awaitable[str]]


def dienstkonto_token(angabe: str) -> TokenQuelle:
    """Liefert Zugriffstokens eines Dienstkontos und erneuert sie bei Bedarf.

    ``angabe`` ist der Pfad zur JSON-Schlüsseldatei oder – für die Cloud, wo es
    keine lokalen Dateien gibt – direkt deren Inhalt.
    """
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    if angabe.lstrip().startswith("{"):
        zugang = service_account.Credentials.from_service_account_info(
            json.loads(angabe), scopes=[SCOPE]
        )
    else:
        zugang = service_account.Credentials.from_service_account_file(
            angabe, scopes=[SCOPE]
        )
    sperre = asyncio.Lock()

    async def token() -> str:
        async with sperre:
            if not zugang.valid:
                # google-auth arbeitet synchron – nicht im Event-Loop des Anrufs blockieren
                await asyncio.to_thread(zugang.refresh, Request())
            return zugang.token

    return token


def _zeit(wert: dt.datetime) -> str:
    return wert.isoformat()


class GoogleKalender:
    def __init__(
        self,
        kalender_id: str,
        token: TokenQuelle,
        zeitzone: str = "Europe/Berlin",
        api: str = API,
    ) -> None:
        self._url = f"{api.rstrip('/')}/calendars/{quote(kalender_id, safe='')}/events"
        self._token = token
        self._tz = ZoneInfo(zeitzone)
        self._zeitzone = zeitzone

    # --- HTTP ---------------------------------------------------------------

    async def _anfrage(
        self,
        methode: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        kopf = {"Authorization": f"Bearer {await self._token()}"}
        async with (
            aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as http,
            http.request(
                methode, url, params=params, json=json, headers=kopf
            ) as antwort,
        ):
            if antwort.status >= 400:
                text = await antwort.text()
                raise RuntimeError(f"Google Calendar {antwort.status}: {text[:300]}")
            if antwort.status == 204:
                return {}
            return await antwort.json()

    async def _events(self, **params: Any) -> list[dict[str, Any]]:
        params = {"singleEvents": "true", "maxResults": "250", **params}
        events: list[dict[str, Any]] = []
        while True:
            seite = await self._anfrage("GET", self._url, params=params)
            events += seite.get("items", [])
            if not (weiter := seite.get("nextPageToken")):
                return events
            params["pageToken"] = weiter

    # --- Umwandlung ---------------------------------------------------------

    def _zeitpunkt(self, angabe: dict[str, str]) -> tuple[dt.datetime, bool]:
        if "dateTime" in angabe:
            return dt.datetime.fromisoformat(
                angabe["dateTime"].replace("Z", "+00:00")
            ), False
        tag = dt.date.fromisoformat(angabe["date"])
        return dt.datetime.combine(tag, dt.time(0), tzinfo=self._tz), True

    def _als_termin(self, event: dict[str, Any]) -> Termin | None:
        if (
            event.get("status") == "cancelled"
            or event.get("transparency") == "transparent"
        ):
            return None
        beginn, ganztaegig = self._zeitpunkt(event["start"])
        ende, _ = self._zeitpunkt(event["end"])
        privat = event.get("extendedProperties", {}).get("private", {})
        return Termin(
            leistung=privat.get("leistung") or event.get("summary", "Belegt"),
            beginn=beginn,
            ende=ende,
            name=privat.get("name", ""),
            telefon=privat.get("telefon_anzeige", ""),
            notiz=privat.get("notiz", ""),
            id=privat.get("smith_id") or event.get("id", ""),
            exklusiv=ganztaegig,
        )

    # --- Kalender-Protokoll -------------------------------------------------

    async def termine_zwischen(
        self, von: dt.datetime, bis: dt.datetime
    ) -> list[Termin]:
        events = await self._events(timeMin=_zeit(von), timeMax=_zeit(bis))
        return [t for e in events if (t := self._als_termin(e))]

    async def buchen(self, termin: Termin) -> Termin:
        beschreibung = [f"Telefon: {termin.telefon}"]
        if termin.notiz:
            beschreibung.append(f"Notiz: {termin.notiz}")
        beschreibung.append("Gebucht von der KI-Telefonassistenz.")
        await self._anfrage(
            "POST",
            self._url,
            json={
                "summary": f"{termin.leistung} – {termin.name}",
                "description": "\n".join(beschreibung),
                "start": {"dateTime": _zeit(termin.beginn), "timeZone": self._zeitzone},
                "end": {"dateTime": _zeit(termin.ende), "timeZone": self._zeitzone},
                "extendedProperties": {
                    "private": {
                        "smith_id": termin.id,
                        "leistung": termin.leistung,
                        "name": termin.name,
                        "telefon": telefon_normalisieren(termin.telefon),
                        "telefon_anzeige": termin.telefon,
                        "notiz": termin.notiz,
                    }
                },
            },
        )
        return termin

    async def termine_von(self, telefon: str, ab: dt.datetime) -> list[Termin]:
        gesucht = telefon_normalisieren(telefon)
        if not gesucht:
            return []
        events = await self._events(
            timeMin=_zeit(ab),
            privateExtendedProperty=f"telefon={gesucht}",
            orderBy="startTime",
        )
        return [t for e in events if (t := self._als_termin(e))]

    async def absagen(self, termin_id: str) -> Termin | None:
        events = await self._events(privateExtendedProperty=f"smith_id={termin_id}")
        for event in events:
            termin = self._als_termin(event)
            if termin is None:
                continue
            await self._anfrage("DELETE", f"{self._url}/{quote(event['id'], safe='')}")
            termin.status = "abgesagt"
            return termin
        return None
