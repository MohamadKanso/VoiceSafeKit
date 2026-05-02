from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from voicesafekit.integrations.openvoiceos import protect_utterance


def handle_voice_transcript(transcript: str) -> dict[str, object]:
    """Example OpenVoiceOS-style hook.

    A real voice assistant would call this after speech-to-text and before the
    transcript is sent to a skill, LLM, or other assistant service.
    """

    safety = protect_utterance(transcript)

    if not safety.should_continue:
        return {
            "send_to_assistant": False,
            "assistant_input": "",
            "message": "This transcript needs urgent human support before an assistant continues.",
            "safety": safety.to_dict(),
        }

    return {
        "send_to_assistant": True,
        "assistant_input": safety.safe_transcript,
        "message": "Use the safer transcript and follow the guidance.",
        "safety": safety.to_dict(),
    }


if __name__ == "__main__":
    fake_transcript = (
        "Please help me reset my account. My email is alex.rivera@example.com "
        "and my password is BlueFalcon2026."
    )
    print(json.dumps(handle_voice_transcript(fake_transcript), indent=2))
