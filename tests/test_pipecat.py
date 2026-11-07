import asyncio

import pytest

pytest.importorskip("pipecat")

from pipecat.frames.frames import (  # noqa: E402
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
)
from pipecat.tests.utils import run_test  # noqa: E402

from voicesafekit import PrivacySession  # noqa: E402
from voicesafekit.integrations.pipecat import (  # noqa: E402
    VoiceSafeContextGuard,
    VoiceSafeInputProcessor,
    VoiceSafeOutputProcessor,
)


def _transcript(text: str) -> TranscriptionFrame:
    return TranscriptionFrame(text=text, user_id="u", timestamp="now")


def test_input_processor_redacts_spoken_pii() -> None:
    processor = VoiceSafeInputProcessor()
    down, _ = asyncio.run(
        run_test(
            processor,
            frames_to_send=[_transcript("my card is four two four two four two four two "
                                        "four two four two four two four two")],
            expected_down_frames=[TranscriptionFrame],
        )
    )
    assert down[0].text == "my card is [CARD_1]"


def test_input_processor_blocks_and_speaks_message() -> None:
    processor = VoiceSafeInputProcessor()
    blocked = []

    @processor.event_handler("on_block")
    async def on_block(_processor, protected):
        blocked.append(protected.decision)

    down, _ = asyncio.run(
        run_test(
            processor,
            frames_to_send=[_transcript("I can't breathe, call an ambulance")],
            expected_down_frames=[TTSSpeakFrame],
        )
    )
    assert blocked == ["BLOCK"]


def test_output_processor_restores_split_placeholders() -> None:
    session = PrivacySession()
    session.protect("my email is alex@example.com")
    processor = VoiceSafeOutputProcessor(session)
    down, _ = asyncio.run(
        run_test(
            processor,
            frames_to_send=[
                LLMFullResponseStartFrame(),
                LLMTextFrame("I'll email [EMA"),
                LLMTextFrame("IL_1] now."),
                LLMFullResponseEndFrame(),
            ],
        )
    )
    text = "".join(f.text for f in down if isinstance(f, LLMTextFrame))
    assert text == "I'll email alex@example.com now."


def test_context_guard_keeps_real_values_out_of_context() -> None:
    session = PrivacySession()
    session.protect("my email is alex@example.com")
    down, _ = asyncio.run(
        run_test(
            VoiceSafeContextGuard(session),
            frames_to_send=[LLMTextFrame("Sent to alex@example.com.")],
        )
    )
    assert down[0].text == "Sent to [EMAIL_1]."
