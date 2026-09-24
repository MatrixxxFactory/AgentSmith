"""Benachrichtigt den Betrieb über neue Buchungen, Absagen und Rückrufbitten.

Kanäle (beliebig kombinierbar, alle optional):
- ntfy:    Push aufs Handy über die kostenlose ntfy-App (https://ntfy.sh)
- E-Mail:  über einen beliebigen SMTP-Server
- Webhook: JSON an n8n, Make, Zapier …

Empfänger und Zugangsdaten stehen NICHT im Profil (das Repo ist öffentlich),
sondern in .env.local. Für mehrere Betriebe gibt es pro Profil eigene Werte:
``SMITH_<PROFIL>_NTFY_THEMA`` hat Vorrang vor ``SMITH_NTFY_THEMA``, wobei
<PROFIL> die Profil-ID in Großbuchstaben mit "_" statt "-" ist.

Versand läuft im Hintergrund: Ein langsamer Dienst darf nie das Telefonat bremsen.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, ClassVar, Protocol
from zoneinfo import ZoneInfo

import aiohttp

from .profil import Profil
from .zeit import WOCHENTAG_ANZEIGE

logger = logging.getLogger("smith.benachrichtigung")

ZEITLIMIT = aiohttp.ClientTimeout(total=10)


@dataclass
class Meldung:
    ereignis: str
    titel: str
    text: str
    dringend: bool
    daten: dict[str, Any]


class Kanal(Protocol):
    name: str

    async def zustellen(self, profil: Profil, meldung: Meldung) -> None: ...


# --- Einstellungen ------------------------------------------------------------


def einstellung(profil: Profil, schluessel: str, standard: str = "") -> str:
    """Liest SMITH_<PROFIL>_<SCHLUESSEL>, sonst SMITH_<SCHLUESSEL>, sonst standard."""
    praefix = profil.id.upper().replace("-", "_")
    return (
        os.getenv(f"SMITH_{praefix}_{schluessel}")
        or os.getenv(f"SMITH_{schluessel}")
        or standard
    )


# --- Texte ----------------------------------------------------------------------


def _zeitpunkt(profil: Profil, iso: str) -> str:
    wert = dt.datetime.fromisoformat(iso).astimezone(
        ZoneInfo(profil.assistent.zeitzone)
    )
    return f"{WOCHENTAG_ANZEIGE[wert.weekday()]}, {wert:%d.%m.%Y um %H:%M} Uhr"


def meldung_bauen(profil: Profil, ereignis: str, daten: dict[str, Any]) -> Meldung:
    """Macht aus einem Ereignis eine kurze, fürs Handy lesbare Nachricht."""
    firma = profil.firma.name
    zeilen: list[str] = []
    dringend = bool(daten.get("dringend"))

    if ereignis in ("termin_gebucht", "termin_abgesagt"):
        titel = (
            f"Neuer Termin – {firma}"
            if ereignis == "termin_gebucht"
            else f"Termin abgesagt – {firma}"
        )
        zeilen += [
            daten.get("leistung", ""),
            _zeitpunkt(profil, daten["beginn"]),
            f"{daten.get('name', '')}, {daten.get('telefon', '')}",
        ]
        if daten.get("notiz"):
            zeilen.append(f"Notiz: {daten['notiz']}")
    elif ereignis == "rueckruf":
        titel = f"{'DRINGEND: ' if dringend else ''}Rückrufbitte – {firma}"
        zeilen += [
            f"{daten.get('name', '')}, {daten.get('telefon', '')}",
            daten.get("anliegen", ""),
        ]
    elif ereignis == "weitergeleitet":
        titel = f"Anruf weitergeleitet – {firma}"
        zeilen += [
            f"Anrufer: {daten.get('anrufer') or 'unbekannt'}",
            f"Grund: {daten.get('grund', '')}",
        ]
    else:
        titel = f"{ereignis} – {firma}"
        zeilen += [f"{k}: {v}" for k, v in daten.items()]

    return Meldung(
        ereignis=ereignis,
        titel=titel,
        text="\n".join(z for z in zeilen if z),
        dringend=dringend,
        daten=daten,
    )


# --- Kanäle ---------------------------------------------------------------------


class NtfyKanal:
    name = "ntfy"
    _TAGS: ClassVar[dict[str, list[str]]] = {
        "termin_gebucht": ["calendar"],
        "termin_abgesagt": ["x"],
        "rueckruf": ["telephone_receiver"],
        "weitergeleitet": ["arrow_right_hook"],
    }

    def __init__(self, server: str, thema: str, token: str = "") -> None:
        self.server = server.rstrip("/")
        self.thema = thema
        self.token = token

    async def zustellen(self, profil: Profil, meldung: Meldung) -> None:
        # JSON-Veröffentlichung, damit Umlaute im Titel sicher ankommen
        nutzlast = {
            "topic": self.thema,
            "title": meldung.titel,
            "message": meldung.text,
            "priority": 5 if meldung.dringend else 3,
            "tags": self._TAGS.get(meldung.ereignis, []),
        }
        kopf = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        async with (
            aiohttp.ClientSession(timeout=ZEITLIMIT) as http,
            http.post(self.server, json=nutzlast, headers=kopf) as antwort,
        ):
            antwort.raise_for_status()


class WebhookKanal:
    name = "webhook"

    def __init__(self, url: str) -> None:
        self.url = url

    async def zustellen(self, profil: Profil, meldung: Meldung) -> None:
        nutzlast = {
            "ereignis": meldung.ereignis,
            "betrieb": profil.firma.name,
            "profil": profil.id,
            "titel": meldung.titel,
            "text": meldung.text,
            "dringend": meldung.dringend,
            "daten": meldung.daten,
        }
        async with (
            aiohttp.ClientSession(timeout=ZEITLIMIT) as http,
            http.post(self.url, json=nutzlast) as antwort,
        ):
            antwort.raise_for_status()


class EmailKanal:
    name = "email"

    def __init__(
        self,
        an: str,
        server: str,
        port: int,
        benutzer: str,
        passwort: str,
        absender: str = "",
    ) -> None:
        self.an = [a.strip() for a in an.split(",") if a.strip()]
        self.server = server
        self.port = port
        self.benutzer = benutzer
        self.passwort = passwort
        self.absender = absender or benutzer

    def _senden(self, nachricht: EmailMessage) -> None:
        if self.port == 465:
            with smtplib.SMTP_SSL(self.server, self.port, timeout=10) as smtp:
                smtp.login(self.benutzer, self.passwort)
                smtp.send_message(nachricht)
        else:
            with smtplib.SMTP(self.server, self.port, timeout=10) as smtp:
                smtp.starttls()
                smtp.login(self.benutzer, self.passwort)
                smtp.send_message(nachricht)

    async def zustellen(self, profil: Profil, meldung: Meldung) -> None:
        nachricht = EmailMessage()
        nachricht["Subject"] = meldung.titel
        nachricht["From"] = (
            f"{profil.assistent.name} (KI-Telefonassistenz) <{self.absender}>"
        )
        nachricht["To"] = ", ".join(self.an)
        if meldung.dringend:
            nachricht["X-Priority"] = "1"
        nachricht.set_content(
            f"{meldung.text}\n\n—\nAutomatisch notiert von {profil.assistent.name}, "
            f"der KI-Telefonassistenz von {profil.firma.name}."
        )
        # smtplib blockiert – deshalb in einem Thread, nie im Event-Loop des Anrufs
        await asyncio.to_thread(self._senden, nachricht)


def kanaele_fuer(profil: Profil) -> list[Kanal]:
    kanaele: list[Kanal] = []

    if thema := einstellung(profil, "NTFY_THEMA"):
        kanaele.append(
            NtfyKanal(
                server=einstellung(profil, "NTFY_SERVER", "https://ntfy.sh"),
                thema=thema,
                token=einstellung(profil, "NTFY_TOKEN"),
            )
        )

    if an := einstellung(profil, "EMAIL_AN"):
        server = einstellung(profil, "SMTP_SERVER")
        benutzer = einstellung(profil, "SMTP_BENUTZER")
        passwort = einstellung(profil, "SMTP_PASSWORT")
        if server and benutzer and passwort:
            kanaele.append(
                EmailKanal(
                    an=an,
                    server=server,
                    port=int(einstellung(profil, "SMTP_PORT", "587")),
                    benutzer=benutzer,
                    passwort=passwort,
                    absender=einstellung(profil, "SMTP_ABSENDER"),
                )
            )
        else:
            logger.warning(
                "EMAIL_AN gesetzt, aber SMTP_SERVER/BENUTZER/PASSWORT fehlen"
            )

    url = einstellung(profil, "WEBHOOK_URL") or profil.benachrichtigung.webhook_url
    if url:
        kanaele.append(WebhookKanal(url))

    return kanaele


# --- Versand --------------------------------------------------------------------


class Benachrichtiger:
    def __init__(self, profil: Profil, kanaele: list[Kanal] | None = None) -> None:
        self._profil = profil
        self.kanaele = kanaele if kanaele is not None else kanaele_fuer(profil)
        self._laufend: set[asyncio.Task[None]] = set()

    async def senden(self, ereignis: str, daten: dict[str, Any]) -> None:
        """Stößt den Versand an und kehrt sofort zurück."""
        meldung = meldung_bauen(self._profil, ereignis, daten)
        logger.info("%s | %s", meldung.titel, meldung.text.replace("\n", " | "))
        for kanal in self.kanaele:
            task = asyncio.create_task(self._zustellen(kanal, meldung))
            self._laufend.add(task)
            task.add_done_callback(self._laufend.discard)

    async def _zustellen(self, kanal: Kanal, meldung: Meldung) -> None:
        try:
            await kanal.zustellen(self._profil, meldung)
        except Exception:
            # Ein Fehler hier darf nie das Telefonat stören – nur protokollieren
            logger.exception("Benachrichtigung über %s fehlgeschlagen", kanal.name)

    async def abschliessen(self, zeitlimit: float = 15) -> None:
        """Wartet am Anrufende, bis alle Nachrichten raus sind."""
        if self._laufend:
            await asyncio.wait(set(self._laufend), timeout=zeitlimit)
