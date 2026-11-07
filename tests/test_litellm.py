"""LiteLLM guardrail: hooks called directly with proxy-shaped data and real LiteLLM objects."""

from __future__ import annotations

import asyncio

import pytest

litellm = pytest.importorskip("litellm")

from litellm.types.utils import (  # noqa: E402
    Delta,
    ModelResponse,
    ModelResponseStream,
    StreamingChoices,
)

from voicesafekit.integrations.litellm import VoiceSafeGuardrail  # noqa: E402

CARD_SPOKEN = ("four two four two " * 4).strip()


def run(coro):
    return asyncio.run(coro)


def request(*messages: dict, call_id: str = "call-1") -> dict:
    return {
        "model": "gpt-4o-mini",
        "messages": list(messages),
        "litellm_call_id": call_id,
        "metadata": {"user_api_key_alias": "test"},
    }


def reply(content: str) -> ModelResponse:
    return ModelResponse(
        model="gpt-4o-mini",
        choices=[
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
    )


def guard(**kwargs) -> VoiceSafeGuardrail:
    return VoiceSafeGuardrail(
        guardrail_name="voicesafekit",
        event_hook=["pre_call", "post_call"],
        default_on=True,
        **kwargs,
    )


def pre(g: VoiceSafeGuardrail, data: dict) -> dict:
    return run(g.async_pre_call_hook(None, None, data, "acompletion"))


def test_pre_call_redacts_and_post_call_restores() -> None:
    g = guard()
    data = pre(
        g,
        request(
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": f"my card is {CARD_SPOKEN}"},
        ),
    )
    assert data["messages"][1]["content"] == "my card is [CARD_1]"
    assert data["messages"][0]["content"] == "Be brief."

    response = run(g.async_post_call_success_hook(data, None, reply("Card [CARD_1] saved.")))
    assert isinstance(response, ModelResponse)
    assert response.choices[0].message.content == f"Card {CARD_SPOKEN} saved."
    assert g._sessions == {}  # forgotten once the reply is out


def test_history_gets_stable_placeholders() -> None:
    g = guard()
    data = pre(
        g,
        request(
            {"role": "user", "content": "email alex@example.com"},
            {"role": "assistant", "content": "Done, I emailed alex@example.com."},
            {"role": "user", "content": "now bob@example.com"},
        ),
    )
    assert [m["content"] for m in data["messages"]] == [
        "email [EMAIL_1]",
        "Done, I emailed [EMAIL_1].",
        "now [EMAIL_2]",
    ]


def test_list_of_parts_content() -> None:
    g = guard()
    image = {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}}
    data = pre(
        g,
        request({"role": "user", "content": [{"type": "text", "text": "a@b.co please"}, image]}),
    )
    assert data["messages"][0]["content"][0]["text"] == "[EMAIL_1] please"
    assert data["messages"][0]["content"][1] == image


def test_block_raises_http_400() -> None:
    fastapi = pytest.importorskip("fastapi")
    g = guard()
    with pytest.raises(fastapi.HTTPException) as caught:
        pre(g, request({"role": "user", "content": "my ssn is 123-45-6789"}))
    assert caught.value.status_code == 400
    assert "VoiceSafeKit" in caught.value.detail["error"]
    assert caught.value.detail["voicesafekit"]["decision"] == "BLOCK"
    assert "123-45-6789" not in str(caught.value.detail)
    assert g._sessions == {}


def test_block_off_forwards_redacted() -> None:
    g = guard(block_on_critical=False)
    data = pre(g, request({"role": "user", "content": "my ssn is 123-45-6789"}))
    assert data["messages"][0]["content"] == "my ssn is [SSN_1]"


def test_requests_do_not_share_values() -> None:
    g = guard()
    pre(g, request({"role": "user", "content": "email alex@example.com"}, call_id="a"))
    other = request({"role": "user", "content": "hello"}, call_id="b")
    pre(g, other)
    response = run(g.async_post_call_success_hook(other, None, reply("Sent to [EMAIL_1].")))
    assert response.choices[0].message.content == "Sent to [EMAIL_1]."


def test_streaming_restores_across_chunks() -> None:
    g = guard()
    data = pre(g, request({"role": "user", "content": "email alex@example.com"}))
    pieces = ["Sending to [EM", "AIL_1", "] now", " [x"]

    async def upstream():
        for i, text in enumerate(pieces):
            yield ModelResponseStream(
                id="chatcmpl-1",
                model="gpt-4o-mini",
                choices=[
                    StreamingChoices(
                        index=0,
                        delta=Delta(content=text),
                        finish_reason="stop" if i == len(pieces) - 1 else None,
                    )
                ],
            )

    async def collect():
        out = []
        async for chunk in g.async_post_call_streaming_iterator_hook(None, upstream(), data):
            out.append(chunk.choices[0].delta.content or "")
        return out

    out = run(collect())
    assert out[0] == "Sending to "
    assert "".join(out) == "Sending to alex@example.com now [x"


def test_streaming_without_finish_reason_flushes_tail() -> None:
    g = guard()
    data = pre(g, request({"role": "user", "content": "email alex@example.com"}))

    async def upstream():
        yield ModelResponseStream(
            id="c", model="m", choices=[StreamingChoices(index=0, delta=Delta(content="To [EMA"))]
        )

    async def collect():
        return [
            chunk.choices[0].delta.content
            async for chunk in g.async_post_call_streaming_iterator_hook(None, upstream(), data)
        ]

    assert "".join(run(collect())) == "To [EMA"


def test_restore_off_keeps_placeholders() -> None:
    g = guard(restore_in_output=False)
    data = pre(g, request({"role": "user", "content": "email alex@example.com"}))
    response = run(g.async_post_call_success_hook(data, None, reply("To [EMAIL_1]")))
    assert response.choices[0].message.content == "To [EMAIL_1]"


def test_text_prompt_and_responses_input() -> None:
    g = guard()
    data = pre(g, {"model": "m", "prompt": "mail a@b.co", "litellm_call_id": "p"})
    assert data["prompt"] == "mail [EMAIL_1]"
    data = pre(
        g,
        {
            "model": "m",
            "litellm_call_id": "r",
            "input": [{"role": "user", "content": [{"type": "input_text", "text": "a@b.co"}]}],
        },
    )
    assert data["input"][0]["content"][0]["text"] == "[EMAIL_1]"


def test_session_store_is_bounded() -> None:
    g = guard(max_sessions=2)
    for i in range(5):
        pre(g, request({"role": "user", "content": "hi"}, call_id=f"c{i}"))
    assert list(g._sessions) == ["c3", "c4"]


def test_config_style_construction() -> None:
    """The proxy calls Class(guardrail_name=..., event_hook=mode, default_on=..., **extra)."""
    g = VoiceSafeGuardrail(
        guardrail_name="voicesafekit",
        event_hook=["pre_call", "post_call"],
        default_on=True,
        spoken=False,
        block_on_critical=False,
    )
    assert g.spoken is False and g.block_on_critical is False
    assert g.should_run_guardrail(data={"metadata": {}}, event_type=_hook("pre_call"))
    assert g.should_run_guardrail(data={"metadata": {}}, event_type=_hook("post_call"))


def _hook(name: str):
    from litellm.types.guardrails import GuardrailEventHooks

    return GuardrailEventHooks(name)
