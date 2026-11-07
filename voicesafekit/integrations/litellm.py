"""LiteLLM proxy integration: a custom guardrail that keeps personal data away from the model.

Add it to the proxy's ``config.yaml``::

    guardrails:
      - guardrail_name: voicesafekit
        litellm_params:
          guardrail: voicesafekit.integrations.litellm.VoiceSafeGuardrail
          mode: [pre_call, post_call]
          default_on: true

What it does on each request:

* ``pre_call``: every user, assistant and tool message (plus a plain ``prompt`` or
  Responses API ``input``) is swapped for placeholders (``[CARD_1]``,
  ``[EMAIL_1]`` ...) before the request leaves the proxy. Spoken forms count
  ("four two four two ..."). If the newest user message is ``BLOCK`` (government
  ID, card security code, an emergency ...) the request is rejected with HTTP 400.
* ``post_call``: placeholders in the reply are turned back into the real values,
  for normal and streamed Chat Completions responses. Other response types keep
  their placeholders (safe, but not restored).

The proxy is stateless, so each request gets its own ``PrivacySession``, kept in
memory from the pre-call hook to the post-call hook under the request's
``litellm_call_id`` (at most ``max_sessions`` at a time). History is redacted in
order, so the same conversation always gets the same placeholder numbers.
Credentials (passwords, PINs, CVVs, one-time codes, API keys) are never stored,
so they are never restored.

Requires ``pip install "voicesafekit[litellm]"`` (LiteLLM proxy).
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from collections.abc import AsyncGenerator
from typing import Any

from litellm.integrations.custom_guardrail import CustomGuardrail
from litellm.types.utils import Delta, ModelResponse, ModelResponseStream, StreamingChoices

from voicesafekit.session import PrivacySession, Protected, StreamRestorer

DEFAULT_BLOCK_MESSAGE = (
    "VoiceSafeKit blocked this request before it reached the model because it "
    "contains something that must not be shared with an AI model."
)
EMERGENCY_HINT = "If this is an emergency, contact your local emergency number now."

_TEXT_ROLES = frozenset({"user", "assistant", "tool", "function"})


class VoiceSafeGuardrail(CustomGuardrail):
    """LiteLLM ``CustomGuardrail`` that redacts requests and restores replies.

    Extra ``litellm_params`` in ``config.yaml`` become keyword arguments:

    Args:
        spoken: Also catch personal data said out loud ("four two four two ...").
        block_on_critical: Reject the request when the newest user message is ``BLOCK``.
        restore_in_output: Put real values back into the reply.
        block_message: First sentence of the 400 error for a blocked request.
        max_sessions: How many in-flight requests' placeholder maps to keep.
    """

    def __init__(
        self,
        *,
        spoken: bool = True,
        block_on_critical: bool = True,
        restore_in_output: bool = True,
        block_message: str = DEFAULT_BLOCK_MESSAGE,
        max_sessions: int = 1000,
        **kwargs: Any,
    ) -> None:
        kwargs.setdefault("guardrail_name", "voicesafekit")
        super().__init__(**kwargs)
        self.spoken = spoken
        self.block_on_critical = block_on_critical
        self.restore_in_output = restore_in_output
        self.block_message = block_message
        self.max_sessions = max(1, max_sessions)
        self._sessions: OrderedDict[str, PrivacySession] = OrderedDict()

    # LiteLLM hooks

    async def async_pre_call_hook(
        self,
        user_api_key_dict: Any,
        cache: Any,
        data: dict,
        call_type: Any,
    ) -> dict:
        session = PrivacySession(spoken=self.spoken)
        latest = self.protect_request(session, data)
        if latest is not None and latest.blocked and self.block_on_critical:
            raise _rejection(self.block_reason(latest), latest)
        self._remember(data, session)
        return data

    async def async_post_call_success_hook(
        self,
        data: dict,
        user_api_key_dict: Any,
        response: Any,
    ) -> Any:
        session = self._forget(data)
        if session is None or not self.restore_in_output:
            return response
        if isinstance(response, ModelResponse):
            for choice in response.choices:
                message = getattr(choice, "message", None)
                content = getattr(message, "content", None)
                if isinstance(content, str):
                    message.content = session.restore(content)
        return response

    async def async_post_call_streaming_iterator_hook(
        self,
        user_api_key_dict: Any,
        response: Any,
        request_data: dict,
    ) -> AsyncGenerator[ModelResponseStream, None]:
        session = self._forget(request_data)
        if session is None or not self.restore_in_output:
            async for chunk in response:
                yield chunk
            return

        restorers: dict[int, StreamRestorer] = {}
        last: ModelResponseStream | None = None
        async for chunk in response:
            if isinstance(chunk, ModelResponseStream):
                last = chunk
                for choice in chunk.choices:
                    index = getattr(choice, "index", 0) or 0
                    delta = getattr(choice, "delta", None)
                    restorer = restorers.setdefault(index, session.stream())
                    if delta is not None and isinstance(delta.content, str):
                        delta.content = restorer.feed(delta.content)
                    if getattr(choice, "finish_reason", None):
                        rest = restorers.pop(index).flush()
                        if rest and delta is not None:
                            delta.content = (delta.content or "") + rest
            yield chunk

        # A stream that ended without finish_reason: emit whatever is still held back.
        for index, restorer in restorers.items():
            rest = restorer.flush()
            if rest and last is not None:
                yield ModelResponseStream(
                    id=last.id,
                    model=last.model,
                    created=last.created,
                    choices=[StreamingChoices(index=index, delta=Delta(content=rest))],
                )

    # logic

    def protect_request(self, session: PrivacySession, data: dict) -> Protected | None:
        """Redact a request body in place. Returns the newest user message's result."""
        latest: Protected | None = None

        def protect(text: str, results: list[Protected], user: bool) -> str:
            if not user:
                text = session.reprotect(text)  # earlier replies carry restored values
            protected = session.protect(text)
            results.append(protected)
            return protected.text

        for message in data.get("messages") or []:
            if not isinstance(message, dict) or message.get("role") not in _TEXT_ROLES:
                continue
            is_user = message.get("role") == "user"
            results: list[Protected] = []
            _map_content(message, lambda t, r=results, u=is_user: protect(t, r, u))
            if is_user and results:
                latest = max(results, key=lambda p: p.blocked)

        prompt = data.get("prompt")
        if isinstance(prompt, str):
            results = []
            data["prompt"] = protect(prompt, results, True)
            latest = results[0]

        items = data.get("input")
        if isinstance(items, str):
            results = []
            data["input"] = protect(items, results, True)
            latest = results[0]
        elif isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                is_user = item.get("role", "user") == "user"
                results = []
                _map_content(item, lambda t, r=results, u=is_user: protect(t, r, u))
                if is_user and results:
                    latest = max(results, key=lambda p: p.blocked)
        return latest

    def block_reason(self, protected: Protected) -> str:
        labels = sorted({f.label for f in protected.result.findings})
        parts = [self.block_message]
        if labels:
            parts.append("Detected: " + ", ".join(labels) + ".")
        if any("emergency" in g.lower() for g in protected.guidance):
            parts.append(EMERGENCY_HINT)
        return " ".join(parts)

    def _remember(self, data: dict, session: PrivacySession) -> None:
        key = data.get("litellm_call_id")
        if not key:
            # The proxy always sets one; direct callers of the hook may not.
            key = data["litellm_call_id"] = str(uuid.uuid4())
        self._sessions[key] = session
        self._sessions.move_to_end(key)
        while len(self._sessions) > self.max_sessions:
            self._sessions.popitem(last=False)

    def _forget(self, data: dict) -> PrivacySession | None:
        key = (data or {}).get("litellm_call_id")
        return self._sessions.pop(key, None) if key else None


def _rejection(message: str, protected: Protected) -> Exception:
    detail = {
        "error": message,
        "voicesafekit": {
            "decision": protected.decision,
            "kinds": sorted({f.kind for f in protected.result.findings}),
        },
    }
    try:
        from fastapi import HTTPException
    except ImportError:  # SDK-only install without the proxy extras
        return ValueError(message)
    return HTTPException(status_code=400, detail=detail)


def _map_content(message: dict, fn) -> None:
    content = message.get("content")
    if isinstance(content, str):
        message["content"] = fn(content)
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                part["text"] = fn(part["text"])
