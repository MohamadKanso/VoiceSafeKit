"""See VoiceSafeKit inside a Pipecat pipeline without any API keys.

    pip install "voicesafekit[pipecat]"
    python examples/pipecat/offline_demo.py

A fake STT frame goes in, a fake LLM echoes what it received, and you can see
exactly what the LLM saw and what the TTS would say. In a real bot, replace the
fake pieces with your STT/LLM/TTS services and keep the three VoiceSafeKit
processors where they are:

    pipeline = Pipeline([
        transport.input(), stt,
        guard_in,                 # before the user aggregator
        user_aggregator, llm,
        restore_out,              # between LLM and TTS
        tts, transport.output(),
        guard_context,            # before the assistant aggregator
        assistant_aggregator,
    ])
"""

import asyncio

from pipecat.frames.frames import (
    Frame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.tests.utils import run_test

from voicesafekit.integrations.pipecat import voicesafe_processors


class FakeLLM(FrameProcessor):
    """Prints what the LLM receives and streams back a reply using its placeholders."""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame):
            print(f"LLM receives : {frame.text}")
            await self.push_frame(LLMFullResponseStartFrame())
            for chunk in ["Thanks [NA", "ME_1]. I'll send the receipt to [EMAIL", "_1]."]:
                await self.push_frame(LLMTextFrame(chunk))
            await self.push_frame(LLMFullResponseEndFrame())
            return
        await self.push_frame(frame, direction)


async def main() -> None:
    from pipecat.pipeline.pipeline import Pipeline

    guard_in, restore_out, _ = voicesafe_processors()

    @guard_in.event_handler("on_decision")
    async def on_decision(_processor, protected):
        print(f"Decision     : {protected.decision} ({len(protected.placeholders)} values hidden)")

    said = (
        "Hi, my name is Alex Rivera. My card number is four two four two four two four two "
        "four two four two four two four two and my email is alex dot rivera at gmail dot com."
    )
    print(f"User says    : {said}")
    down, _ = await run_test(
        Pipeline([guard_in, FakeLLM(), restore_out]),
        frames_to_send=[TranscriptionFrame(text=said, user_id="user", timestamp="now")],
    )
    spoken = "".join(f.text for f in down if isinstance(f, LLMTextFrame))
    print(f"TTS says     : {spoken}")


if __name__ == "__main__":
    asyncio.run(main())
