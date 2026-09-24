"""Der Telefonagent selbst: setzt Profil, Module und Prompt zusammen."""

from __future__ import annotations

from typing import Any

from livekit.agents import Agent, RunContext, ToolError
from livekit.agents.beta.tools import EndCallTool

from .module import AnrufKontext, aktive_module
from .prompt import systemprompt


class Auflegen(EndCallTool):
    """Wie EndCallTool, legt aber nicht auf, solange etwas nur vorgemerkt ist.

    Aus der Simulation: Die Anruferin korrigierte ihre Nummer und verabschiedete sich
    im selben Satz. Das Modell sagte "gebucht" und legte sofort auf – gebucht war aber
    nur vorgemerkt, weil die neue Nummer nie vorgelesen wurde.
    """

    def __init__(self, kontext: AnrufKontext, **kwargs: Any) -> None:
        self._kontext = kontext
        self._verweigert_bei: int | None = None
        super().__init__(**kwargs)

    async def _end_call(self, ctx: RunContext) -> Any | None:
        beitraege = self._kontext.beitraege()
        # Nur einmal pro Gesprächszug verweigern – sonst drohen Endlosschleifen
        if (
            self._kontext.unbestaetigt_vorgemerkt()
            and self._verweigert_bei != beitraege
        ):
            self._verweigert_bei = beitraege
            raise ToolError(
                "Noch nicht auflegen: Ein Termin bzw. eine Absage ist nur vorgemerkt, NICHT "
                "erledigt. Lies dem Anrufer die Zusammenfassung vor und frag, ob sie stimmt."
            )
        return await super()._end_call(ctx)


class Rezeptionist(Agent):
    def __init__(self, kontext: AnrufKontext) -> None:
        self.kontext = kontext
        self.module = aktive_module(kontext)
        super().__init__(
            instructions=systemprompt(
                kontext.profil, self.module, kontext.uhr(), kontext.anrufer_nummer
            ),
            tools=[
                *self.module,
                Auflegen(
                    kontext,
                    # Kein Nachsatz nach dem Auflegen: Die Verabschiedung steht schon im
                    # selben Zug (siehe Prompt). Eine zweite Antwort brachte Gemma dazu,
                    # auf Englisch laut über sich selbst nachzudenken.
                    end_instructions=None,
                    ignore_on_enter=True,
                ),
            ],
        )

    async def on_enter(self) -> None:
        # Für die Rückfrage-Pflicht beim Buchen/Absagen: Wie oft hat der Anrufer
        # schon gesprochen? Gezählt wird im echten Gesprächsverlauf.
        session = self.session
        self.kontext.beitraege = lambda: sum(
            1
            for eintrag in session.history.items
            if getattr(eintrag, "role", None) == "user"
        )
        # Die Begrüßung kommt fest aus dem Profil: schneller als eine LLM-Antwort
        # und immer genau so, wie der Betrieb es möchte.
        session.say(self.kontext.profil.assistent.begruessung)
