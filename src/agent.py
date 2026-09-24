import logging
from collections.abc import AsyncIterable

from dotenv import load_dotenv
from livekit.agents import (
    NOT_GIVEN,
    Agent,
    AgentFalseInterruptionEvent,
    AgentSession,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    ModelSettings,
    RoomInputOptions,
    WorkerOptions,
    ChatContext,
    FunctionTool,
    cli,
    metrics,
)
from livekit.plugins import cartesia, deepgram, noise_cancellation, openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from pydantic_core import from_json
from pydantic import BaseModel

from typing import cast

logger = logging.getLogger("agent")

load_dotenv(".env.local")


class JSONAssistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions='You are a helpful voice AI assistant. Respond in JSON with a "response" field.'
        )

    async def _process_json(self, text: AsyncIterable[str]) -> AsyncIterable[str]:
        last_response = ""
        acc_text = ""
        not_json = None  # None until first chunk is seen
        async for chunk in text:
            if not_json is None:
                not_json = not chunk.startswith("{")
            if not_json:
                yield chunk
                continue

            acc_text += chunk
            try:
                resp: dict = from_json(acc_text, allow_partial="trailing-strings")
            except ValueError:
                continue

            response = resp.get("response", "")
            delta = (
                response[len(last_response) :]
                if response.startswith(last_response)
                else response
            )
            if delta:
                yield delta
                last_response = response

    async def tts_node(self, text: AsyncIterable[str], model_settings: ModelSettings):
        return Agent.default.tts_node(self, self._process_json(text), model_settings)

    async def transcription_node(
        self, text: AsyncIterable[str], model_settings: ModelSettings
    ):
        return Agent.default.transcription_node(
            self, self._process_json(text), model_settings
        )


class StructuredOutputAssistant(Agent):
    def __init__(self) -> None:
        self._openai_llm = openai.LLM(model="gpt-4o-mini")
        super().__init__(
            instructions="You are a helpful voice AI assistant.", llm=self._openai_llm
        )

    class Response(BaseModel):
        spoken_response: str

    async def llm_node(
        self,
        chat_ctx: ChatContext,
        tools: list[FunctionTool],
        model_settings: ModelSettings,
    ):
        tool_choice = model_settings.tool_choice if model_settings else NOT_GIVEN
        async with self._openai_llm.chat(
            chat_ctx=chat_ctx,
            tools=tools,
            tool_choice=tool_choice,
            response_format=self.Response,
        ) as stream:
            async for chunk in stream:
                yield chunk

    async def _process_response(self, text: AsyncIterable[str]) -> AsyncIterable[str]:
        last_response = ""
        acc_text = ""
        async for chunk in text:
            acc_text += chunk
            try:
                resp: self.Response = from_json(
                    acc_text, allow_partial="trailing-strings"
                )
            except ValueError:
                continue

            response = resp.spoken_response
            delta = (
                response[len(last_response) :]
                if response.startswith(last_response)
                else response
            )
            if delta:
                yield delta
                last_response = resp.response

    async def tts_node(self, text: AsyncIterable[str], model_settings: ModelSettings):
        return Agent.default.tts_node(
            self, self._process_response(text), model_settings
        )

    async def transcription_node(
        self, text: AsyncIterable[str], model_settings: ModelSettings
    ):
        return Agent.default.transcription_node(
            self, self._process_response(text), model_settings
        )


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    session = AgentSession(
        llm=openai.LLM(model="gpt-4o-mini"),
        stt=deepgram.STT(model="nova-3", language="multi"),
        tts=cartesia.TTS(voice="6f84f4b8-58a2-430c-8c79-688dad597532"),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )

    # To use a realtime model instead of a voice pipeline, use the following session setup instead:
    # session = AgentSession(
    #     # See all providers at https://docs.livekit.io/agents/integrations/realtime/
    #     llm=openai.realtime.RealtimeModel()
    # )

    @session.on("agent_false_interruption")
    def _on_agent_false_interruption(ev: AgentFalseInterruptionEvent):
        logger.info("false positive interruption, resuming")
        session.generate_reply(instructions=ev.extra_instructions or NOT_GIVEN)

    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    async def log_usage():
        summary = usage_collector.get_summary()
        logger.info(f"Usage: {summary}")

    ctx.add_shutdown_callback(log_usage)

    # # Optional: Add a virtual avatar to the session
    # avatar = hedra.AvatarSession(
    #   avatar_id="...",  # See https://docs.livekit.io/agents/integrations/avatar/hedra
    # )
    # # Start the avatar and wait for it to join
    # await avatar.start(session, room=ctx.room)

    await session.start(
        agent=StructuredOutputAssistant(),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )

    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
