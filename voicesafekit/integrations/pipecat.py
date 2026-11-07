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

import asyncio
import re

from pipecat.frames.frames import (
    EndFrame,
    Frame,
    InterimTranscriptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TextFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    UserStoppedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from voicesafekit.session import PrivacySession, StreamRestorer
from voicesafekit.spoken import (
    REPEATERS,
    SENSITIVE_KEYWORDS,
    TEENS,
    TENS,
    UNITS,
)

_NUMBER_WORDS = set(UNITS) | set(TEENS) | set(TENS) | set(REPEATERS) | {"hundred", "plus"}
_TURN_END_FRAMES = (UserStoppedSpeakingFrame, VADUserStoppedSpeakingFrame, EndFrame)


def ends_mid_value(text: str) -> bool:
    """True when a transcript fragment probably stops in the middle of a value.

    "my card number is four two four two" or "my card number is" are held back
    so the rest of the number, arriving in the next STT frame, is checked with
    its context. Ordinary speech ("set a timer for five") is never held because
    no sensitive keyword is nearby.
    """
    tokens = re.findall(r"[a-z]+|\d+", text.lower())
    if not tokens or not any(t in SENSITIVE_KEYWORDS for t in tokens[-8:]):
        return False
    last = tokens[-1]
    if last.isdigit() or last in _NUMBER_WORDS:
        return True
    if last in SENSITIVE_KEYWORDS:
        return True
    return last in {"is", "was", "are"} and len(tokens) > 1 and tokens[-2] in SENSITIVE_KEYWORDS

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
        hold_split_values: Many STT services send several final transcriptions per
            turn. When one ends mid-number near a sensitive word, hold it and merge
            it with the next one so a card number split across frames is caught.
        hold_timeout: Longest time (seconds) a fragment is held before it is
            checked and forwarded on its own.
    """

    def __init__(
        self,
        session: PrivacySession | None = None,
        *,
        block_message: str | None = DEFAULT_BLOCK_MESSAGE,
        drop_blocked: bool = True,
        hold_split_values: bool = True,
        hold_timeout: float = 0.8,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.session = session or PrivacySession()
        self._block_message = block_message
        self._drop_blocked = drop_blocked
        self._hold = hold_split_values
        self._hold_timeout = hold_timeout
        self._pending: TranscriptionFrame | None = None
        self._pending_direction = FrameDirection.DOWNSTREAM
        self._flush_task: asyncio.Task | None = None
        self._register_event_handler("on_decision")
        self._register_event_handler("on_block")

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            if self._pending is not None:
                frame.text = f"{self._pending.text.rstrip()} {frame.text.lstrip()}"
                self._pending = None
                await self._cancel_flush()
            if self._hold and ends_mid_value(frame.text):
                self._pending = frame
                self._pending_direction = direction
                self._flush_task = self.create_task(self._flush_after_timeout())
                return
            await self._emit(frame, direction)
            return

        if isinstance(frame, _TURN_END_FRAMES):
            await self._cancel_flush()
            await self._flush_pending()
        elif isinstance(frame, InterimTranscriptionFrame):
            # Interim text can reach UIs and logs; never let it carry raw values.
            frame.text = self.session.protect(frame.text).text

        await self.push_frame(frame, direction)

    async def cleanup(self) -> None:
        await self._cancel_flush()
        await super().cleanup()

    async def _emit(self, frame: TranscriptionFrame, direction: FrameDirection) -> None:
        protected = self.session.protect(frame.text)
        await self._call_event_handler("on_decision", protected)
        if protected.blocked:
            await self._call_event_handler("on_block", protected)
            if self._block_message:
                await self.push_frame(TTSSpeakFrame(self._block_message), direction)
            if self._drop_blocked:
                return
        frame.text = protected.text
        await self.push_frame(frame, direction)

    async def _flush_pending(self) -> None:
        if self._pending is not None:
            frame, self._pending = self._pending, None
            await self._emit(frame, self._pending_direction)

    async def _flush_after_timeout(self) -> None:
        await asyncio.sleep(self._hold_timeout)
        self._flush_task = None
        await self._flush_pending()

    async def _cancel_flush(self) -> None:
        task, self._flush_task = self._flush_task, None
        if task is not None and task is not asyncio.current_task():
            await self.cancel_task(task)


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
