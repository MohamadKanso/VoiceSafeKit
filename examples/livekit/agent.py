"""A LiveKit voice agent that never sends spoken PII to the LLM.

    pip install "voicesafekit[livekit]"
    python examples/livekit/agent.py dev

Set LIVEKIT_URL, LIVEKIT_API_KEY and LIVEKIT_API_SECRET first. The models below
use LiveKit Inference model strings; swap in any STT/LLM/TTS plugin you like.
"""

from livekit.agents import AgentServer, AgentSession, JobContext, cli

from voicesafekit.integrations.livekit import VoiceSafeAgent


class Assistant(VoiceSafeAgent):
    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are a helpful voice assistant. Personal details in the user's "
                "messages appear as placeholders like [CARD_1] or [EMAIL_1]. Use the "
                "placeholders as-is when you need to refer to them; never ask the user "
                "to repeat a card number, PIN or one-time code."
            )
        )


server = AgentServer()


@server.rtc_session()
async def entrypoint(ctx: JobContext) -> None:
    session = AgentSession(
        stt="deepgram/nova-3",
        llm="openai/gpt-4.1-mini",
        tts="cartesia/sonic-2",
    )
    await session.start(agent=Assistant(), room=ctx.room)


if __name__ == "__main__":
    cli.run_app(server)
