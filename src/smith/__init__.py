"""Agent Smith – modularer KI-Telefonagent für kleine Betriebe.

Aufbau:
    profil.py        Branchenprofil (YAML) laden und prüfen
    zeit.py          Öffnungszeiten-Logik
    module/          Fähigkeiten (Info, Termine, Rückruf, Weiterleitung …)
    speicher/        Wo Termine und Nachrichten landen (austauschbar)
    prompt.py        Systemprompt aus Profil + Modulen
    rezeptionist.py  Der LiveKit-Agent
"""

from __future__ import annotations

from .benachrichtigung import Benachrichtiger, einstellung
from .module import AnrufKontext
from .profil import PROJEKT_ROOT, Profil, profil_waehlen
from .rezeptionist import Rezeptionist
from .speicher import Kalender
from .speicher.google_kalender import GoogleKalender, dienstkonto_token
from .speicher.json_ablage import JsonAblage

DATEN_ORDNER = PROJEKT_ROOT / "daten"


def kalender_fuer(profil: Profil, ablage: JsonAblage) -> Kalender:
    if profil.kalender.art == "datei":
        return ablage
    kalender_id = einstellung(profil, "GOOGLE_KALENDER_ID")
    dienstkonto = einstellung(profil, "GOOGLE_DIENSTKONTO")
    if not (kalender_id and dienstkonto):
        raise RuntimeError(
            f"Profil {profil.id} nutzt Google Calendar, aber in .env.local fehlen "
            "SMITH_GOOGLE_KALENDER_ID und/oder SMITH_GOOGLE_DIENSTKONTO"
        )
    return GoogleKalender(
        kalender_id,
        dienstkonto_token(dienstkonto),
        zeitzone=profil.assistent.zeitzone,
    )


def anruf_kontext(profil: Profil, anrufer_nummer: str = "") -> AnrufKontext:
    """Verdrahtet die Bausteine passend zum Profil."""
    ablage = JsonAblage(DATEN_ORDNER / profil.id)
    return AnrufKontext(
        profil=profil,
        kalender=kalender_fuer(profil, ablage),
        postfach=ablage,
        protokoll=ablage,
        benachrichtiger=Benachrichtiger(profil),
        anrufer_nummer=anrufer_nummer,
    )


__all__ = [
    "DATEN_ORDNER",
    "AnrufKontext",
    "JsonAblage",
    "Profil",
    "Rezeptionist",
    "anruf_kontext",
    "kalender_fuer",
    "profil_waehlen",
]
