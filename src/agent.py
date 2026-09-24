"""Einstiegspunkt für LiveKit (muss src/agent.py bleiben: Dockerfile und CLI erwarten ihn).

Hier wird nur verdrahtet. Was der Agent kann und für welchen Betrieb er
spricht, steht im Profil unter profile/ und in den Modulen unter src/smith/.
"""

import logging

from dotenv import load_dotenv
from livekit import rtc
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
from livekit.plugins import ai_coustics

from smith import Rezeptionist, anruf_kontext, profil_waehlen

logger = logging.getLogger("agent")

load_dotenv(".env.local")

server = AgentServer()


@server.rtc_session(agent_name="agent-smith")
async def anruf(ctx: JobContext):
    anrufer_nummer = ""
    angerufene_nummer = ""

    # Bei echten Anrufen erst auf den Anrufer warten: Seine SIP-Attribute
    # verraten, welche Nummer gewählt wurde – und damit, welcher Betrieb gemeint ist.
    # Im Konsolenmodus (`lk agent console`) gibt es keinen Anrufer.
    if not ctx.is_fake_job():
        await ctx.connect()
        teilnehmer = await ctx.wait_for_participant()
        if teilnehmer.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
            anrufer_nummer = teilnehmer.attributes.get("sip.phoneNumber", "")
            angerufene_nummer = teilnehmer.attributes.get("sip.trunkPhoneNumber", "")

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
