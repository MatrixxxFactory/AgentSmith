"""Auskunft: Öffnungszeiten an bestimmten Tagen und Wissensfragen."""

from __future__ import annotations

import datetime as dt
import re

from livekit.agents import ToolError, function_tool

from ..zeit import (
    WOCHENTAG_ANZEIGE,
    datum_sprechen,
    sonderzeit_fuer,
    zeiten_am,
    zeiten_text,
)
from .basis import Modul

# Ab so vielen FAQ-Einträgen wandert das Wissen aus dem Prompt in ein Such-Tool
FAQ_IM_PROMPT_MAX = 12


def datum_parsen(
    text: str, wochentag: str = "", heute: dt.date | None = None
) -> dt.date:
    """Liest JJJJ-MM-TT und prüft, ob es zum genannten Wochentag passt.

    Sprachmodelle verrechnen sich bei Wochentagen gern um einen Tag. Hier fällt das
    auf, bevor ein Termin am falschen Tag landet.
    """
    try:
        datum = dt.date.fromisoformat(text.strip())
    except ValueError as e:
        raise ToolError(
            f"Ungültiges Datum '{text}'. Bitte im Format JJJJ-MM-TT übergeben."
        ) from e

    kuerzel = wochentag.strip().lower()[:2]
    namen = [t.lower()[:2] for t in WOCHENTAG_ANZEIGE]
    if kuerzel in namen:
        genannt = namen.index(kuerzel)
        if datum.weekday() != genannt:
            ab = heute or datum
            naechster = ab + dt.timedelta(days=(genannt - ab.weekday()) % 7)
            raise ToolError(
                f"{datum.isoformat()} ist ein {WOCHENTAG_ANZEIGE[datum.weekday()]}, kein "
                f"{WOCHENTAG_ANZEIGE[genannt]}. Der nächste {WOCHENTAG_ANZEIGE[genannt]} "
                f"ist {naechster.isoformat()}. Nimm das richtige Datum aus dem Kalender."
            )
    return datum


def _woerter(text: str) -> set[str]:
    # Grober Wortstamm (erste 6 Buchstaben), damit "Parkplätzen" auch "Parkplätze" findet
    return {w[:6] for w in re.findall(r"\w+", text.lower()) if len(w) > 3}


class InfoModul(Modul):
    name = "info"

    def __init__(self, kontext) -> None:
        super().__init__(kontext)
        if not self._faq_als_tool:
            self._tools = [t for t in self._tools if t.id != "wissen_nachschlagen"]

    @property
    def _faq_als_tool(self) -> bool:
        return len(self.k.profil.faq) > FAQ_IM_PROMPT_MAX

    def anweisungen(self) -> str:
        if self._faq_als_tool:
            return (
                "Für Fragen, die oben nicht beantwortet sind, nutze zuerst `wissen_nachschlagen`. "
                "Findet es nichts, sag ehrlich, dass du es nicht weißt."
            )
        return ""

    @function_tool
    async def oeffnungszeiten_am(self, datum: str, wochentag: str = "") -> str:
        """Liefert die Öffnungszeiten an einem bestimmten Datum, inklusive Feiertagen und Betriebsurlaub.

        Nutze das, wenn jemand nach einem konkreten Tag fragt (z. B. "Haben Sie am 24. Dezember offen?").

        Args:
            datum: Datum im Format JJJJ-MM-TT
            wochentag: Der Wochentag, den der Anrufer genannt hat (z. B. Mittwoch), zur Kontrolle des Datums. Leer lassen, wenn er keinen genannt hat.
        """
        heute = self.k.uhr().date()
        tag = datum_parsen(datum, wochentag, heute)
        text = f"{datum_sprechen(tag, heute)}: {zeiten_text(zeiten_am(self.k.profil, tag))}"
        sonder = sonderzeit_fuer(self.k.profil, tag)
        if sonder and sonder.hinweis:
            text += f" ({sonder.hinweis})"
        return text

    @function_tool
    async def wissen_nachschlagen(self, frage: str) -> str:
        """Sucht in den hinterlegten Antworten des Betriebs nach einer passenden Auskunft.

        Args:
            frage: Die Frage des Anrufers in eigenen Worten
        """
        gesucht = _woerter(frage)
        treffer = sorted(
            self.k.profil.faq,
            key=lambda f: len(gesucht & _woerter(f.frage + " " + f.antwort)),
            reverse=True,
        )
        treffer = [
            f for f in treffer[:3] if gesucht & _woerter(f.frage + " " + f.antwort)
        ]
        if not treffer:
            return "Dazu ist nichts hinterlegt."
        return "\n".join(f"F: {f.frage}\nA: {f.antwort}" for f in treffer)
