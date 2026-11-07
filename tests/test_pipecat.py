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


def test_number_split_across_frames_is_merged_and_caught() -> None:
    parts = [
        "my card number is four two four two",
        "four two four two four two four two four two four two",
    ]
    down, _ = asyncio.run(
        run_test(
            VoiceSafeInputProcessor(),
            frames_to_send=[_transcript(t) for t in parts],
            expected_down_frames=[TranscriptionFrame],
        )
    )
    assert down[0].text == "my card number is [CARD_1]"


def test_keyword_at_end_of_frame_waits_for_the_value() -> None:
    down, _ = asyncio.run(
        run_test(
            VoiceSafeInputProcessor(),
            frames_to_send=[
                _transcript("my social security number is"),
                _transcript("four seven one five five eight eight four three"),
            ],
            expected_down_frames=[TTSSpeakFrame],
        )
    )
    # Blocked as an SSN; nothing raw is forwarded.
    assert all("four seven" not in getattr(f, "text", "") for f in down)


def test_held_fragment_is_flushed_at_end_of_pipeline() -> None:
    down, _ = asyncio.run(
        run_test(
            VoiceSafeInputProcessor(),
            frames_to_send=[_transcript("my pin is four eight two one")],
        )
    )
    texts = [f.text for f in down if isinstance(f, TranscriptionFrame)]
    assert texts == ["my pin is [PIN_1]"]


def test_held_fragment_is_flushed_after_timeout() -> None:
    async def scenario():
        processor = VoiceSafeInputProcessor(hold_timeout=0.05)
        return await run_test(
            processor,
            frames_to_send=[_transcript("my card ends in 4821")],
            expected_down_frames=[TranscriptionFrame],
        )

    down, _ = asyncio.run(scenario())
    assert down[0].text == "my [CARD_LAST4_1]"


def test_ordinary_number_endings_are_not_held() -> None:
    from voicesafekit.integrations.pipecat import ends_mid_value

    assert not ends_mid_value("set a timer for five")
    assert not ends_mid_value("I have two kids and one dog")
    assert ends_mid_value("my card number is four two four two")
    assert ends_mid_value("my card number is")
    assert ends_mid_value("my social security number is")
