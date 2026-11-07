"""Pipecat integration: privacy filtering for real-time voice agents.

Drop the processors into a Pipecat pipeline::

    from voicesafekit.integrations.pipecat import voicesafe_processors

    guard_in, restore_out, guard_context = voicesafe_processors()

    pipeline = Pipeline([
        transport.input(),
        stt,
        guard_in,            # spoken PII -> [EMAIL_1], [CARD_1] ... before the LLM
        user_aggregator,
        llm,
        restore_out,         # [EMAIL_1] -> real value, so the voice can say it
        tts,
        transport.output(),
        guard_context,       # keeps real values out of the stored assistant reply
        assistant_aggregator,
    ])

Events on the input processor: ``on_decision(processor, protected)`` for every
final transcript and ``on_block(processor, protected)`` when a transcript is
blocked (emergency, government ID, card security code ...).

Requires ``pip install "voicesafekit[pipecat]"``.
"""

from __future__ import annotations

from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TextFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from voicesafekit.session import PrivacySession, StreamRestorer

DEFAULT_BLOCK_MESSAGE = (
    "I can't pass that on to the assistant. If this is an emergency, "
    "please contact your local emergency number now."
)


class VoiceSafeInputProcessor(FrameProcessor):
    """Redacts personal data in transcriptions before they reach the LLM.

    Args:
        session: Shared ``PrivacySession``. Pass the same one to the output
            processor so replies can be restored.
        block_message: Spoken when a transcript is blocked. ``None`` to stay silent.
        drop_blocked: Drop blocked transcripts instead of forwarding them redacted.
    """

    def __init__(
        self,
        session: PrivacySession | None = None,
        *,
        block_message: str | None = DEFAULT_BLOCK_MESSAGE,
        drop_blocked: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.session = session or PrivacySession()
        self._block_message = block_message
        self._drop_blocked = drop_blocked
        self._register_event_handler("on_decision")
        self._register_event_handler("on_block")

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            protected = self.session.protect(frame.text)
            await self._call_event_handler("on_decision", protected)
            if protected.blocked:
                await self._call_event_handler("on_block", protected)
                if self._block_message:
                    await self.push_frame(TTSSpeakFrame(self._block_message), direction)
                if self._drop_blocked:
                    return
            frame.text = protected.text
        elif isinstance(frame, InterimTranscriptionFrame):
            # Interim text can reach UIs and logs; never let it carry raw values.
            frame.text = self.session.protect(frame.text).text

        await self.push_frame(frame, direction)


class VoiceSafeOutputProcessor(FrameProcessor):
    """Restores placeholders in streamed LLM text before it reaches TTS."""

    def __init__(self, session: PrivacySession, **kwargs) -> None:
        super().__init__(**kwargs)
        self.session = session
        self._stream: StreamRestorer = session.stream()

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMFullResponseStartFrame):
            self._stream = self.session.stream()
        elif isinstance(frame, LLMTextFrame):
            text = self._stream.feed(frame.text)
            if not text:
                return  # holding back a partial placeholder
            frame.text = text
        elif isinstance(frame, LLMFullResponseEndFrame):
            rest = self._stream.flush()
            if rest:
                await self.push_frame(LLMTextFrame(rest), direction)

        await self.push_frame(frame, direction)


class VoiceSafeContextGuard(FrameProcessor):
    """Swaps restored values back to placeholders before the assistant aggregator."""

    def __init__(self, session: PrivacySession, **kwargs) -> None:
        super().__init__(**kwargs)
        self.session = session

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TextFrame) and not isinstance(
            frame, (TranscriptionFrame, InterimTranscriptionFrame)
        ):
            frame.text = self.session.reprotect(frame.text)
            raw = getattr(frame, "raw_text", None)
            if raw:
                frame.raw_text = self.session.reprotect(raw)
        await self.push_frame(frame, direction)


def voicesafe_processors(
    session: PrivacySession | None = None, **input_kwargs
) -> tuple[VoiceSafeInputProcessor, VoiceSafeOutputProcessor, VoiceSafeContextGuard]:
    """Create the input filter, output restorer and context guard sharing one session."""
    session = session or PrivacySession()
    return (
        VoiceSafeInputProcessor(session, **input_kwargs),
        VoiceSafeOutputProcessor(session),
        VoiceSafeContextGuard(session),
    )
