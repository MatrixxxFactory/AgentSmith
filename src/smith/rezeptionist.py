"""Der Telefonagent selbst: setzt Profil, Module und Prompt zusammen."""

from __future__ import annotations

from livekit.agents import Agent
from livekit.agents.beta.tools import EndCallTool

from .module import AnrufKontext, aktive_module
from .prompt import systemprompt


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
                EndCallTool(
                    end_instructions="Verabschiede dich kurz und freundlich auf Deutsch.",
                    ignore_on_enter=True,
                ),
            ],
        )

    async def on_enter(self) -> None:
        # Die Begrüßung kommt fest aus dem Profil: schneller als eine LLM-Antwort
        # und immer genau so, wie der Betrieb es möchte.
        self.session.say(self.kontext.profil.assistent.begruessung)
