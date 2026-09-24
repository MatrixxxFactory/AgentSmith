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

from .benachrichtigung import Benachrichtiger
from .module import AnrufKontext
from .profil import PROJEKT_ROOT, Profil, profil_waehlen
from .rezeptionist import Rezeptionist
from .speicher.json_ablage import JsonAblage

DATEN_ORDNER = PROJEKT_ROOT / "daten"


def anruf_kontext(profil: Profil, anrufer_nummer: str = "") -> AnrufKontext:
    """Verdrahtet die Standard-Bausteine. Hier später z. B. Google Calendar einsetzen."""
    ablage = JsonAblage(DATEN_ORDNER / profil.id)
    return AnrufKontext(
        profil=profil,
        kalender=ablage,
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
    "profil_waehlen",
]
