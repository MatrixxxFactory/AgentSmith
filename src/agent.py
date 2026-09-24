"""Einstiegspunkt für LiveKit (muss src/agent.py bleiben: Dockerfile und CLI erwarten ihn).

Hier wird nur verdrahtet. Was der Agent kann und für welchen Betrieb er
spricht, steht im Profil unter profile/ und in den Modulen unter src/smith/.
"""

import asyncio
import logging

from dotenv import load_dotenv
from livekit import api
from livekit.agents import (
    AgentServer,
    AgentSession,
    JobContext,
    STTContextOptions,
    TurnHandlingOptions,
    cli,
    inference,
    room_io,
)
from livekit.agents.worker import ServerEnvOption
from livekit.plugins import ai_coustics

from smith import Rezeptionist, anruf_kontext, profil_waehlen

logger = logging.getLogger("agent")

load_dotenv(".env.local")

# Vorgewärmte Prozesse, damit ein Anruf sofort angenommen wird. Im Dev-Modus
# (lk agent dev, Startdatei) wären es sonst 0: Jeder Anruf wartete dann ~3 s auf
# einen neuen Prozess, und bei mehreren gleichzeitigen Anrufen blieb einer hängen.
server = AgentServer(
    num_idle_processes=ServerEnvOption(
        dev_default=2,
        prod_default=AgentServer._default_num_idle_processes.prod_default,
    )
)


# Präfix der Räume, die unsere SIP-Weiterleitungsregel anlegt (telefonie/dispatch-regel.json)
TELEFON_RAUM_PRAEFIX = "anruf-"
SIP_WARTEZEIT_S = 3.0


async def _sip_attribute(ctx: JobContext) -> dict[str, str]:
    """SIP-Attribute des Anrufers, falls es ein Telefonanruf ist – sonst {}.

    Abgefragt über die Server-API, OHNE sich mit dem Raum zu verbinden: Die
    Reihenfolge "erst Sitzung starten, dann verbinden" (wie in der LiveKit-Vorlage)
    bleibt so erhalten. Umgekehrt blockierte unter Windows das Laden der
    Zertifikate direkt nach dem Verbinden den Prozess, bis die LiveKit-Bibliothek
    mit einer FFI-Panic abstürzte und keine Anrufe mehr annahm.

    Nur in Telefon-Räumen wird kurz gewartet; nie unbegrenzt, denn ein Agent,
    der nicht startet, ist ein unbeantworteter Anruf.
    """
    raum = ctx.job.room.name
    if not raum.startswith(TELEFON_RAUM_PRAEFIX):
        return {}
    ende = asyncio.get_running_loop().time() + SIP_WARTEZEIT_S
    while True:
        try:
            antwort = await ctx.api.room.list_participants(
                api.ListParticipantsRequest(room=raum)
            )
            for teilnehmer in antwort.participants:
                if teilnehmer.kind == api.ParticipantInfo.Kind.SIP:
                    return dict(teilnehmer.attributes)
        except Exception:
            logger.exception("Teilnehmer von %s nicht abrufbar", raum)
        if asyncio.get_running_loop().time() >= ende:
            logger.warning(
                "Kein SIP-Anrufer nach %s s – starte mit Standardprofil",
                SIP_WARTEZEIT_S,
            )
            return {}
        await asyncio.sleep(0.25)


@server.rtc_session(agent_name="agent-smith")
async def anruf(ctx: JobContext):
    # Bei Telefonanrufen verraten die SIP-Attribute, welche Nummer gewählt wurde –
    # und damit, welcher Betrieb gemeint ist (mehrere Betriebe pro Agent).
    attribute = {} if ctx.is_fake_job() else await _sip_attribute(ctx)
    anrufer_nummer = attribute.get("sip.phoneNumber", "")
    angerufene_nummer = attribute.get("sip.trunkPhoneNumber", "")

    profil = profil_waehlen(angerufene_nummer)
    kontext = anruf_kontext(profil, anrufer_nummer)
    stimme = profil.stimme
    sprache = profil.assistent.sprache

    ctx.log_context_fields = {"room": ctx.room.name, "profil": profil.id}
    logger.info("Anruf für %s (Profil %s)", profil.firma.name, profil.id)

    session = AgentSession(
        # Modelle über LiveKit Inference; welche Deutsch können, steht in der README
        stt=inference.STT(model=stimme.stt, language=sprache),
        stt_context_options=STTContextOptions(
            keyterms=profil.stt_schluesselwoerter,
            keyterm_detection={"enabled": True},
        ),
        llm=inference.LLM(model=stimme.llm),
        tts=inference.TTS(model=stimme.tts, voice=stimme.voice, language=sprache),
        turn_handling=TurnHandlingOptions(
            turn_detection=inference.TurnDetector(),
            interruption={"mode": "adaptive"},
            preemptive_generation={"enabled": True},
        ),
        expressive=stimme.expressive,
    )

    async def anruf_protokollieren() -> None:
        # Gesprächsverlauf für den Betrieb ablegen (daten/<profil>/anrufe/)
        try:
            await kontext.protokoll.anruf_speichern(
                {
                    "profil": profil.id,
                    "anrufer": anrufer_nummer,
                    "verlauf": session.history.to_dict(),
                }
            )
        except Exception:
            logger.exception("Anrufprotokoll konnte nicht gespeichert werden")
        # Noch laufende Benachrichtigungen nicht mit dem Prozess abbrechen
        await kontext.benachrichtiger.abschliessen()

    ctx.add_shutdown_callback(anruf_protokollieren)

    await session.start(
        agent=Rezeptionist(kontext),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=ai_coustics.audio_enhancement(
                    model=ai_coustics.EnhancerModel.QUAIL_VF_S
                ),
            ),
        ),
    )

    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(server)
