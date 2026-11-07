import asyncio

import pytest

pytest.importorskip("livekit.agents")

from livekit.agents import Agent, StopResponse, llm  # noqa: E402

from voicesafekit.integrations.livekit import VoiceSafeAgent, VoiceSafeRedactor  # noqa: E402


def _message(text: str) -> llm.ChatMessage:
    return llm.ChatMessage(role="user", content=[text])


def test_user_turn_is_protected_before_llm() -> None:
    agent = VoiceSafeAgent(instructions="test")
    message = _message("my email is alex dot rivera at gmail dot com")
    asyncio.run(agent.on_user_turn_completed(llm.ChatContext(), message))
    assert message.content == ["my email is [EMAIL_1]"]


def test_blocked_turn_stops_the_response() -> None:
    agent = VoiceSafeAgent(instructions="test", block_message=None)
    message = _message("my social security number is 471-55-8843")
    with pytest.raises(StopResponse):
        asyncio.run(agent.on_user_turn_completed(llm.ChatContext(), message))
    assert "471" not in message.content[0]


def test_tts_node_restores_values(monkeypatch) -> None:
    agent = VoiceSafeAgent(instructions="test")
    agent.privacy.protect("my email is alex@example.com")
    spoken: list[str] = []

    async def fake_tts_node(_agent, text, _settings):
        async for chunk in text:
            spoken.append(chunk)
        yield "frame"

    monkeypatch.setattr(Agent.default, "tts_node", staticmethod(fake_tts_node))

    async def reply():
        for chunk in ["Sent to [EMA", "IL_1]."]:
            yield chunk

    async def run():
        return [f async for f in agent.tts_node(reply(), None)]

    assert asyncio.run(run()) == ["frame"]
    assert "".join(spoken) == "Sent to alex@example.com."


def test_redactor_is_idempotent() -> None:
    redactor = VoiceSafeRedactor()
    once = redactor.redact("my pin is four eight two one and email a@b.co")
    assert once == "my pin is [PIN removed] and email [email removed]"
    assert redactor.redact(once) == once
