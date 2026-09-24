"""Grundgerüst für Module.

Ein Modul bündelt eine Fähigkeit des Telefonagenten: seine Tools und den
Abschnitt im Systemprompt, der erklärt, wann sie zu benutzen sind. Ob ein
Modul mitläuft, entscheidet allein das Branchenprofil.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import ClassVar

from livekit.agents.llm import Toolset

from ..benachrichtigung import Benachrichtiger
from ..profil import Profil
from ..speicher import Anrufprotokoll, Kalender, Postfach
from ..zeit import jetzt


@dataclass
class AnrufKontext:
    """Alles, was die Module während eines Anrufs brauchen."""

    profil: Profil
    kalender: Kalender
    postfach: Postfach
    protokoll: Anrufprotokoll
    benachrichtiger: Benachrichtiger
    anrufer_nummer: str = ""
    # In Tests austauschbar, damit "heute" nicht vom echten Datum abhängt
    uhr: Callable[[], dt.datetime] = field(default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.uhr is None:
            self.uhr = lambda: jetzt(self.profil)


class Modul(Toolset):
    name: ClassVar[str]

    def __init__(self, kontext: AnrufKontext) -> None:
        self.k = kontext
        super().__init__(id=self.name)

    @classmethod
    def ist_aktiv(cls, profil: Profil) -> bool:
        return True

    def anweisungen(self) -> str:
        """Abschnitt für den Systemprompt. Kurz halten – jedes Token kostet Latenz."""
        return ""
