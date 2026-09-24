"""Registry aller Module.

Neues Modul hinzufügen:
1. Datei in diesem Ordner anlegen, Klasse von ``Modul`` ableiten
2. ``ist_aktiv`` (liest das Profil), ``anweisungen`` und Tools implementieren
3. Klasse unten in ``ALLE_MODULE`` eintragen
"""

from __future__ import annotations

from .basis import AnrufKontext, Modul
from .info import InfoModul
from .rueckruf import RueckrufModul
from .termine import TermineModul
from .weiterleitung import WeiterleitungModul

ALLE_MODULE: list[type[Modul]] = [
    InfoModul,
    TermineModul,
    RueckrufModul,
    WeiterleitungModul,
]


def aktive_module(kontext: AnrufKontext) -> list[Modul]:
    return [cls(kontext) for cls in ALLE_MODULE if cls.ist_aktiv(kontext.profil)]


__all__ = ["ALLE_MODULE", "AnrufKontext", "Modul", "aktive_module"]
