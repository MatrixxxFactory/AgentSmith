"""Benachrichtigt den Betrieb über neue Buchungen, Absagen und Rückrufbitten."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .profil import Profil

logger = logging.getLogger("smith.benachrichtigung")


class Benachrichtiger:
    def __init__(self, profil: Profil) -> None:
        self._profil = profil
        self._url = profil.benachrichtigung.webhook_url

    async def senden(self, ereignis: str, daten: dict[str, Any]) -> None:
        """Ein Fehler hier darf nie das Telefonat stören – nur protokollieren."""
        logger.info("Ereignis %s für %s: %s", ereignis, self._profil.id, daten)
        if not self._url:
            return
        nutzlast = {
            "ereignis": ereignis,
            "betrieb": self._profil.firma.name,
            "daten": daten,
        }
        try:
            async with (
                aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as http,
                http.post(self._url, json=nutzlast) as antwort,
            ):
                if antwort.status >= 400:
                    logger.warning("Webhook antwortete mit Status %s", antwort.status)
        except Exception:
            logger.exception("Webhook %s nicht erreichbar", self._url)
