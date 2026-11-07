"""Open WebUI filter: bodies in the shapes Open WebUI's backend passes to Filter hooks.

Shapes follow open-webui v0.13 ``backend/open_webui/utils/middleware.py``: ``inlet`` gets
the chat-completion form data (OpenAI-style messages) plus ``__metadata__`` /
``__chat_id__``; ``outlet`` gets ``{"model", "messages": [{id, role, content, ...}],
"chat_id", "session_id", "id"}``; ``stream`` gets each raw upstream event.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("pydantic")

from voicesafekit.integrations.openwebui import Filter, VoiceSafeOpenWebUI  # noqa: E402

CARD_SPOKEN = "four two four two " * 4
USER = {"id": "user-1", "name": "Alex", "role": "user"}


def run(coro):
    return asyncio.run(coro)


def inlet_body(*messages: dict) -> dict:
    return {
        "model": "llama3.2:latest",
        "stream": True,
        "messages": list(messages),
        "features": {"voice": True},
    }


def metadata(chat_id: str = "chat-1", message_id: str = "msg-a1") -> dict:
    return {
        "user_id": USER["id"],
        "chat_id": chat_id,
        "message_id": message_id,
        "session_id": "sid-1",
    }


def call_inlet(flt: Filter, body: dict, chat_id: str = "chat-1") -> dict:
    meta = metadata(chat_id)
    return run(flt.inlet(body, __user__=dict(USER), __metadata__=meta, __chat_id__=chat_id))


def outlet_body(messages: list[dict], chat_id: str = "chat-1") -> dict:
    return {
        "model": "llama3.2:latest",
        "messages": messages,
        "filter_ids": [],
        "chat_id": chat_id,
        "session_id": "sid-1",
        "id": messages[-1]["id"],
    }


def test_inlet_redacts_spoken_card_and_outlet_restores() -> None:
    flt = Filter()
    body = call_inlet(
        flt,
        inlet_body(
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": f"my card is {CARD_SPOKEN.strip()}"},
        ),
    )
    assert body["messages"][1]["content"] == "my card is [CARD_1]"
    assert body["messages"][0]["content"] == "You are helpful."

    out = outlet_body(
        [
            {"id": "u1", "role": "user", "content": f"my card is {CARD_SPOKEN.strip()}"},
            {"id": "a1", "role": "assistant", "content": "Got it, card [CARD_1] is saved."},
        ]
    )
    result = run(flt.outlet(out, __user__=dict(USER), __metadata__=metadata()))
    assert result["messages"][1]["content"] == f"Got it, card {CARD_SPOKEN.strip()} is saved."


def test_second_request_in_same_chat_reuses_placeholders() -> None:
    flt = Filter()
    call_inlet(flt, inlet_body({"role": "user", "content": "email me at alex@example.com"}))
    # Turn two: history comes back from the UI with the restored reply.
    body = call_inlet(
        flt,
        inlet_body(
            {"role": "user", "content": "email me at alex@example.com"},
            {"role": "assistant", "content": "Sure, I'll email alex@example.com."},
            {"role": "user", "content": "and bob@example.com, also alex@example.com"},
        ),
    )
    texts = [m["content"] for m in body["messages"]]
    assert texts == [
        "email me at [EMAIL_1]",
        "Sure, I'll email [EMAIL_1].",
        "and [EMAIL_2], also [EMAIL_1]",
    ]


def test_chats_and_users_do_not_share_placeholders() -> None:
    flt = Filter()
    call_inlet(flt, inlet_body({"role": "user", "content": "email alex@example.com"}), "chat-1")
    other = outlet_body(
        [{"id": "a9", "role": "assistant", "content": "Sent to [EMAIL_1]."}], "chat-2"
    )
    result = run(flt.outlet(other, __user__=dict(USER)))
    assert result["messages"][0]["content"] == "Sent to [EMAIL_1]."

    stranger = {"id": "user-2"}
    same_chat = outlet_body([{"id": "a9", "role": "assistant", "content": "Sent to [EMAIL_1]."}])
    result = run(flt.outlet(same_chat, __user__=stranger))
    assert result["messages"][0]["content"] == "Sent to [EMAIL_1]."


def test_block_raises_with_user_facing_message() -> None:
    flt = Filter()
    with pytest.raises(Exception) as caught:
        call_inlet(flt, inlet_body({"role": "user", "content": "my ssn is 123-45-6789"}))
    assert "VoiceSafeKit" in str(caught.value)
    assert "123-45-6789" not in str(caught.value)


def test_block_valve_off_forwards_redacted_text() -> None:
    flt = Filter()
    flt.valves = flt.Valves(block_on_critical=False)
    body = call_inlet(flt, inlet_body({"role": "user", "content": "my ssn is 123-45-6789"}))
    assert body["messages"][0]["content"] == "my ssn is [SSN_1]"


def test_only_newest_user_message_can_block() -> None:
    flt = Filter()
    body = call_inlet(
        flt,
        inlet_body(
            {"role": "user", "content": "my ssn is 123-45-6789"},
            {"role": "assistant", "content": "I can't take that."},
            {"role": "user", "content": "ok, what's the weather?"},
        ),
    )
    assert body["messages"][0]["content"] == "my ssn is [SSN_1]"


def test_list_of_parts_content() -> None:
    flt = Filter()
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
    body = call_inlet(
        flt,
        inlet_body(
            {
                "role": "user",
                "content": [{"type": "text", "text": "send it to alex@example.com"}, image],
            }
        ),
    )
    parts = body["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "send it to [EMAIL_1]"}
    assert parts[1] == image


def test_stream_restores_split_placeholder_in_chat_chunks() -> None:
    flt = Filter()
    call_inlet(flt, inlet_body({"role": "user", "content": "email alex@example.com"}))
    chunks = ["Sending to [EM", "AIL_", "1] now", "."]
    out = []
    for i, text in enumerate(chunks):
        event = {
            "id": "chatcmpl-1",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": text},
                    "finish_reason": "stop" if i == len(chunks) - 1 else None,
                }
            ],
        }
        result = run(
            flt.stream(
                event,
                __user__=dict(USER),
                __metadata__=metadata(),
                __chat_id__="chat-1",
                __message_id__="msg-a1",
            )
        )
        out.append(result["choices"][0]["delta"]["content"])
    assert out[0] == "Sending to "
    assert "".join(out) == "Sending to alex@example.com now."


def test_stream_holds_back_tail_until_finish_reason() -> None:
    flt = Filter()
    call_inlet(flt, inlet_body({"role": "user", "content": "email alex@example.com"}))
    kwargs = {"__user__": dict(USER), "__chat_id__": "chat-1", "__message_id__": "m"}
    first = {"choices": [{"index": 0, "delta": {"content": "costs [CA"}, "finish_reason": None}]}
    last = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
    a = run(flt.stream(first, **kwargs))["choices"][0]["delta"]["content"]
    b = run(flt.stream(last, **kwargs))["choices"][0]["delta"]["content"]
    assert (a, b) == ("costs ", "[CA")


def test_stream_responses_api_events() -> None:
    flt = Filter()
    call_inlet(flt, inlet_body({"role": "user", "content": "email alex@example.com"}))
    kwargs = {"__user__": dict(USER), "__chat_id__": "chat-1", "__message_id__": "m"}
    deltas = [
        {"type": "response.output_text.delta", "item_id": "it", "delta": "To [EMAIL"},
        {"type": "response.output_text.delta", "item_id": "it", "delta": "_1]!"},
    ]
    streamed = "".join(run(flt.stream(e, **kwargs))["delta"] for e in deltas)
    assert streamed == "To alex@example.com!"

    done = {"type": "response.output_text.done", "item_id": "it", "text": "To [EMAIL_1]!"}
    assert run(flt.stream(done, **kwargs))["text"] == "To alex@example.com!"
    message = {"type": "message", "content": [{"type": "output_text", "text": "To [EMAIL_1]!"}]}
    completed = {"type": "response.completed", "response": {"output": [message]}}
    result = run(flt.stream(completed, **kwargs))
    assert result["response"]["output"][0]["content"][0]["text"] == "To alex@example.com!"


def test_restore_in_output_off_keeps_placeholders() -> None:
    flt = Filter()
    flt.valves = flt.Valves(restore_in_output=False)
    call_inlet(flt, inlet_body({"role": "user", "content": "email alex@example.com"}))
    out = outlet_body([{"id": "a1", "role": "assistant", "content": "Sent to [EMAIL_1]."}])
    result = run(flt.outlet(out, __user__=dict(USER)))
    assert result["messages"][0]["content"] == "Sent to [EMAIL_1]."


def test_direct_api_call_without_chat_id_uses_metadata_token() -> None:
    flt = Filter()
    meta = {"user_id": USER["id"], "chat_id": "", "message_id": None, "session_id": None}
    run(
        flt.inlet(
            inlet_body({"role": "user", "content": "email alex@example.com"}),
            __user__=dict(USER),
            __metadata__=meta,
            __chat_id__="",
        )
    )
    out = {"model": "m", "messages": [{"role": "assistant", "content": "To [EMAIL_1]"}]}
    result = run(flt.outlet(out, __user__=dict(USER), __metadata__=meta))
    assert result["messages"][0]["content"] == "To alex@example.com"
    # A different request (fresh metadata) cannot see that value.
    fresh = {"model": "m", "messages": [{"role": "assistant", "content": "To [EMAIL_1]"}]}
    result = run(flt.outlet(fresh, __user__=dict(USER), __metadata__={"chat_id": ""}))
    assert result["messages"][0]["content"] == "To [EMAIL_1]"


def test_session_cache_is_bounded() -> None:
    core = VoiceSafeOpenWebUI(max_chats=3)
    for i in range(10):
        core.inlet({"messages": [{"role": "user", "content": "hi"}]}, chat_id=f"c{i}")
    assert len(core._sessions) == 3
    assert core.session_for("c9") is not None
    assert core.session_for("c0") is None


def test_credentials_are_redacted_and_never_restored() -> None:
    flt = Filter()
    body = call_inlet(flt, inlet_body({"role": "user", "content": "my password is BlueFalcon2026"}))
    assert "BlueFalcon2026" not in body["messages"][0]["content"]
    out = outlet_body([{"id": "a1", "role": "assistant", "content": "Saved [SECRET_1]."}])
    result = run(flt.outlet(out, __user__=dict(USER)))
    assert "BlueFalcon2026" not in result["messages"][0]["content"]


def test_example_function_file_loads_like_open_webui() -> None:
    """Mimic Open WebUI's loader: parse the frontmatter, exec the source, build Filter()."""
    import pathlib
    import re
    import types

    path = (
        pathlib.Path(__file__).parent.parent / "examples" / "openwebui" / "voicesafekit_filter.py"
    )
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert lines[0].strip() == '"""'
    front = {}
    for line in lines[1:]:
        if '"""' in line:
            break
        match = re.match(r"^\s*([a-z_]+):\s*(.*)\s*$", line, re.IGNORECASE)
        if match:
            front[match.group(1)] = match.group(2).strip()
    assert front["requirements"].startswith("voicesafekit @ git+https://")
    for old in ("from utils", "from apps", "from main", "from config"):
        assert old not in content  # Open WebUI rewrites these imports

    module = types.ModuleType("function_voicesafekit_test")
    exec(content, module.__dict__)
    flt = module.Filter()
    assert hasattr(flt, "valves") and hasattr(module.Filter, "Valves")
    body = call_inlet(flt, inlet_body({"role": "user", "content": "email alex@example.com"}))
    assert body["messages"][0]["content"] == "email [EMAIL_1]"
