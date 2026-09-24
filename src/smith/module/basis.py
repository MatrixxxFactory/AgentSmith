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

from livekit.agents import ToolError
from livekit.agents.llm import Toolset

from ..benachrichtigung import Benachrichtiger
from ..profil import Profil
from ..speicher import Anrufprotokoll, Kalender, Postfach
from ..zeit import jetzt

MIN_ZIFFERN = 6


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
    # Wie oft der Anrufer bisher gesprochen hat. Der Rezeptionist verbindet das mit
    # dem Gesprächsverlauf; ohne ihn (Tests) zählt anrufer_hat_gesprochen() mit.
    beitraege: Callable[[], int] = field(default=None)  # type: ignore[assignment]
    _zaehler: int = field(default=0, repr=False)
    # Vorgemerkte, noch nicht bestätigte Aktionen aller Module -> Anruferbeitrag beim Vormerken
    vorgemerkt: dict[tuple, int] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.uhr is None:
            self.uhr = lambda: jetzt(self.profil)
        if self.beitraege is None:
            self.beitraege = lambda: self._zaehler

    def anrufer_hat_gesprochen(self) -> None:
        self._zaehler += 1

    def unbestaetigt_vorgemerkt(self) -> bool:
        """True, wenn in diesem Zug etwas vorgemerkt wurde, das der Anrufer noch nicht gehört hat."""
        jetzt_beitraege = self.beitraege()
        return any(stand == jetzt_beitraege for stand in self.vorgemerkt.values())

    def rueckrufnummer(self, angabe: str) -> str:
        """Genannte Nummer oder – wenn leer – die Anrufernummer. Wirft ToolError ohne gültige Nummer.

        Sprachmodelle tragen sonst gern "unbekannt" oder "die vom Anruf" als Nummer ein.
        """
        nummer = (angabe or "").strip()
        if nummer and sum(z.isdigit() for z in nummer) < MIN_ZIFFERN:
            nummer = ""  # kein Zahlenwert -> wie "nicht genannt" behandeln
        nummer = nummer or self.anrufer_nummer
        if sum(z.isdigit() for z in nummer) < MIN_ZIFFERN:
            hinweis = (
                "Die Nummer des Anrufers ist nicht sichtbar (unterdrückt). "
                if not self.anrufer_nummer
                else ""
            )
            raise ToolError(
                f"{hinweis}Es fehlt eine gültige Rückrufnummer. Frag danach; ohne Nummer "
                "geht es nicht. Möchte der Anrufer keine nennen, biete an, dass er sich "
                "später noch einmal meldet."
            )
        return nummer


class Bestaetigung:
    """Erzwingt "erst vorlesen, dann Ja abwarten" – unabhängig vom Sprachmodell.

    Sprachmodelle fragen gern "Soll ich buchen?" und buchen im selben Atemzug.
    Eine Aktion wird deshalb beim ersten Aufruf nur vorgemerkt; ausgeführt wird
    sie erst, wenn derselbe Aufruf wiederkommt, nachdem der Anrufer gesprochen hat.
    """

    def __init__(self, kontext: AnrufKontext) -> None:
        self._k = kontext

    def freigegeben(self, kern: tuple, details: tuple = ()) -> bool:
        """True, wenn die Aktion ausgeführt werden darf; sonst wird sie vorgemerkt.

        ``kern`` bestimmt, was bestätigt werden muss (z. B. Leistung und Uhrzeit).
        ``details`` (z. B. Name, Nummer) darf der Anrufer nach dem Vorlesen noch
        korrigieren, ohne dass alles erneut vorgelesen wird – er hat die Korrektur ja
        selbst diktiert. Ohne diese Ausnahme gerieten Modelle in eine Schleife, wenn
        Korrektur und Abschied in einem Satz kamen.
        """
        jetzt_beitraege = self._k.beitraege()
        for schluessel, stand in list(self._k.vorgemerkt.items()):
            if schluessel[: len(kern)] == kern and jetzt_beitraege > stand:
                del self._k.vorgemerkt[schluessel]
                return True
        self._k.vorgemerkt[(*kern, *details)] = jetzt_beitraege
        return False


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
