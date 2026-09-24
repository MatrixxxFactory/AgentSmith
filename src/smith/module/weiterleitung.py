"""Weiterleitung an einen Menschen per SIP REFER (Cold Transfer).

Doku: https://docs.livekit.io/telephony/features/transfers/cold/
Der SIP-Trunk muss Weiterleitungen erlauben (bei Twilio "Call Transfer" aktivieren).
"""

from __future__ import annotations

import logging

from livekit import api, rtc
from livekit.agents import RunContext, ToolError, function_tool, get_job_context

from ..profil import Profil
from ..zeit import ist_offen
from .basis import Modul

logger = logging.getLogger("smith.weiterleitung")


class WeiterleitungModul(Modul):
    name = "weiterleitung"

    @classmethod
    def ist_aktiv(cls, profil: Profil) -> bool:
        return profil.module.weiterleitung.aktiv

    def anweisungen(self) -> str:
        einst = self.k.profil.module.weiterleitung
        anlaesse = (
            "Leite weiter bei: " + "; ".join(einst.anlaesse) + ". "
            if einst.anlaesse
            else "Leite weiter, wenn der Anrufer ausdrücklich einen Menschen sprechen möchte "
            "oder du ihm nicht weiterhelfen kannst. "
        )
        return (
            f"Weiterleitung: {anlaesse}Sag vorher kurz, dass du verbindest, und rufe dann "
            "`an_mitarbeiter_weiterleiten` auf. Schlägt es fehl, biete einen Rückruf an."
        )

    def _pruefen(self) -> str | None:
        """Grund, warum gerade nicht weitergeleitet werden kann – oder None."""
        einst = self.k.profil.module.weiterleitung
        if einst.nur_waehrend_oeffnungszeiten and not ist_offen(
            self.k.profil, self.k.uhr()
        ):
            return "Außerhalb der Öffnungszeiten ist niemand erreichbar. Biete einen Rückruf an."
        return None

    @function_tool
    async def an_mitarbeiter_weiterleiten(self, context: RunContext, grund: str) -> str:
        """Verbindet den Anrufer mit einem Mitarbeiter des Betriebs.

        Args:
            grund: Kurz, warum weitergeleitet wird
        """
        if hindernis := self._pruefen():
            raise ToolError(hindernis)

        job = get_job_context()
        anrufer = next(
            (
                p
                for p in job.room.remote_participants.values()
                if p.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
            ),
            None,
        )
        if anrufer is None:
            raise ToolError(
                "Weiterleiten geht nur bei echten Telefonanrufen. Biete stattdessen einen Rückruf an."
            )

        # Erst die Ansage ("Ich verbinde Sie …") zu Ende sprechen lassen
        await context.wait_for_playout()
        nummer = self.k.profil.module.weiterleitung.nummer
        logger.info("Leite %s weiter an %s (%s)", anrufer.identity, nummer, grund)
        try:
            await job.api.sip.transfer_sip_participant(
                api.TransferSIPParticipantRequest(
                    room_name=job.room.name,
                    participant_identity=anrufer.identity,
                    transfer_to=f"tel:{nummer}",
                    play_dialtone=False,
                )
            )
        except Exception as e:
            logger.exception("Weiterleitung fehlgeschlagen")
            raise ToolError(
                "Die Weiterleitung hat nicht geklappt, gerade ist niemand frei. Biete einen Rückruf an."
            ) from e
        await self.k.benachrichtiger.senden(
            "weitergeleitet", {"grund": grund, "anrufer": self.k.anrufer_nummer}
        )
        return "Weitergeleitet."
