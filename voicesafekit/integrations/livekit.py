"""LiveKit Agents integration.

Subclass ``VoiceSafeAgent`` instead of ``Agent``::

    from voicesafekit.integrations.livekit import VoiceSafeAgent

    class Assistant(VoiceSafeAgent):
        def __init__(self) -> None:
            super().__init__(instructions="You are a helpful voice assistant.")

What it does:

* ``on_user_turn_completed`` swaps spoken personal data in the user's turn for
  placeholders (``[CARD_1]``, ``[EMAIL_1]`` ...) before the LLM sees it.
  Blocked turns (emergencies, government IDs, card security codes) are answered
  with ``block_message`` and never reach the LLM.
* ``tts_node`` puts the real values back into the reply so the voice can say
  "I've sent it to alex at example dot com", while the chat context and the
  on-screen transcript keep the placeholders.

``VoiceSafeRedactor`` is a stateless, idempotent ``redact(text) -> str`` for
log and transcript redaction hooks.

Requires ``pip install "voicesafekit[livekit]"``.
"""

from __future__ import annotations

from collections.abc import AsyncIterable
from typing import Any

from livekit.agents import Agent, StopResponse

from voicesafekit.engine import analyze_transcript
from voicesafekit.session import PrivacySession

DEFAULT_BLOCK_MESSAGE = (
    "I can't pass that on. If this is an emergency, please contact your local "
    "emergency number now."
)


class VoiceSafeAgent(Agent):
    """A LiveKit ``Agent`` that keeps personal data out of the LLM."""

    def __init__(
        self,
        *args: Any,
        privacy_session: PrivacySession | None = None,
        block_message: str | None = DEFAULT_BLOCK_MESSAGE,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.privacy = privacy_session or PrivacySession()
        self.block_message = block_message
        self.last_protected = None

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:  # type: ignore[override]
        blocked = False
        content = []
        for item in new_message.content:
            if isinstance(item, str):
                protected = self.privacy.protect(item)
                self.last_protected = protected
                blocked = blocked or protected.blocked
                item = protected.text
            content.append(item)
        new_message.content = content

        if blocked:
            if self.block_message:
                self.session.say(self.block_message, add_to_chat_ctx=False)
            raise StopResponse()

        await super().on_user_turn_completed(turn_ctx, new_message)

    async def tts_node(self, text: AsyncIterable[str], model_settings):  # type: ignore[override]
        async def restored() -> AsyncIterable[str]:
            stream = self.privacy.stream()
            async for chunk in text:
                out = stream.feed(chunk)
                if out:
                    yield out
            rest = stream.flush()
            if rest:
                yield rest

        async for frame in Agent.default.tts_node(self, restored(), model_settings):
            yield frame


class VoiceSafeRedactor:
    """Stateless, idempotent redactor: ``redact(text) -> str``.

    Running it twice gives the same output, which makes it safe for transcript
    and log redaction hooks that may see the same text more than once.
    """

    def __init__(self, *, spoken: bool = True) -> None:
        self.spoken = spoken

    def redact(self, text: str) -> str:
        return analyze_transcript(text, spoken=self.spoken).safe_transcript
