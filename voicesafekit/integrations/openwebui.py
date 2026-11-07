"""Open WebUI integration: a Filter Function that keeps personal data away from the model.

Paste ``examples/openwebui/voicesafekit_filter.py`` into Open WebUI
(Admin Panel > Functions > New Function), or import the filter yourself::

    from voicesafekit.integrations.openwebui import Filter

What the filter does on each turn:

* ``inlet``: every user, assistant and tool message's text is swapped for
  placeholders (``[CARD_1]``, ``[EMAIL_1]`` ...) before the model sees it. Spoken
  forms count ("four two four two ..."), so voice mode is covered. If the newest
  user message is ``BLOCK`` (government ID, card security code, an emergency ...)
  and ``block_on_critical`` is on, the turn stops with a clear message instead.
* ``request``: the same redaction on every model call of a tool-using turn
  (Open WebUI versions that have the ``request`` hook).
* ``stream``: placeholders in the streamed reply are turned back into the real
  values, so the user sees them on their own screen. A placeholder split across
  chunks is held back until it is complete.
* ``outlet``: the same restore on the finished reply.

Placeholders are kept per chat (and per user) in memory, at most
``max_chats`` chats at a time; the oldest are forgotten first. Credentials
(passwords, PINs, CVVs, one-time codes, API keys) are never stored, so they are
never restored. Because a chat's history is redacted in order, the numbering is
the same when a forgotten chat is picked up again.

Not covered: Open WebUI's background tasks (title, tags, follow-up suggestions,
autocomplete) call the task model directly and do not run Filter Functions.
Turn them off, or point them at a local model, if no personal data may leave.

``VoiceSafeOpenWebUI`` holds the logic with no Open WebUI or pydantic
dependency; ``Filter`` is the thin Open WebUI wrapper and needs pydantic, which
Open WebUI always ships.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from typing import Any

from voicesafekit.session import PrivacySession, Protected, StreamRestorer

DEFAULT_BLOCK_MESSAGE = (
    "VoiceSafeKit stopped this message before it reached the model because it "
    "contains something that must not be shared with an AI assistant."
)
EMERGENCY_HINT = "If this is an emergency, contact your local emergency number now."

_SESSION_TOKEN_KEY = "voicesafekit_session"
_TEXT_ROLES = frozenset({"user", "assistant", "tool"})


class VoiceSafeOpenWebUI:
    """Framework-free core of the Open WebUI filter.

    Args:
        spoken: Also catch personal data said out loud ("four two four two ...").
        block_on_critical: Stop the turn when the newest user message is ``BLOCK``.
        restore_in_output: Put real values back into the reply the user sees.
        max_chats: How many chats' placeholder maps to keep in memory.
        block_message: First sentence of the error shown for a blocked turn.
    """

    def __init__(
        self,
        *,
        spoken: bool = True,
        block_on_critical: bool = True,
        restore_in_output: bool = True,
        max_chats: int = 200,
        block_message: str = DEFAULT_BLOCK_MESSAGE,
    ) -> None:
        self.spoken = spoken
        self.block_on_critical = block_on_critical
        self.restore_in_output = restore_in_output
        self.max_chats = max(1, max_chats)
        self.block_message = block_message
        self._sessions: OrderedDict[tuple[str, str], PrivacySession] = OrderedDict()
        self._streams: OrderedDict[tuple[Any, ...], StreamRestorer] = OrderedDict()

    # hooks

    def inlet(
        self,
        body: dict,
        *,
        chat_id: str | None = None,
        user_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """Redact every message; raise ``ValueError`` if the newest user turn is blocked."""
        _, session = self._session(body, chat_id, user_id, metadata, create=True)
        assert session is not None
        latest = self._protect_messages(session, body)
        if latest is not None and latest.blocked and self.block_on_critical:
            raise ValueError(self.block_reason(latest))
        return body

    def request(
        self,
        body: dict,
        *,
        chat_id: str | None = None,
        user_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """Redact the payload of one model call (idempotent; never blocks)."""
        _, session = self._session(body, chat_id, user_id, metadata, create=True)
        assert session is not None
        self._protect_messages(session, body)
        return body

    def outlet(
        self,
        body: dict,
        *,
        chat_id: str | None = None,
        user_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """Restore placeholders in the assistant messages of a finished turn."""
        if not self.restore_in_output:
            return body
        _, session = self._session(body, chat_id, user_id, metadata, create=False)
        if session is None:
            return body
        for message in body.get("messages") or []:
            if isinstance(message, dict) and message.get("role") == "assistant":
                _map_content(message, session.restore)
        return body

    def stream(
        self,
        event: dict,
        *,
        chat_id: str | None = None,
        message_id: str | None = None,
        user_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """Restore placeholders in one streamed event.

        Handles Chat Completions chunks (``choices[].delta.content``) and Responses
        API events (``response.output_text.delta`` and the ``*.done`` /
        ``response.completed`` events that repeat the full text).
        """
        if not self.restore_in_output or not isinstance(event, dict):
            return event
        session_key, session = self._session({}, chat_id, user_id, metadata, create=False)
        if session is None:
            return event
        base = (session_key, message_id or "")

        for choice in event.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            key = (*base, "choice", choice.get("index", 0))
            delta = choice.get("delta")
            if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                delta["content"] = self._restorer(key, session).feed(delta["content"])
            message = choice.get("message")
            if isinstance(message, dict):
                _map_content(message, session.restore)
            if choice.get("finish_reason"):
                rest = self._end_stream(key)
                if rest:
                    if not isinstance(delta, dict):
                        delta = choice["delta"] = {}
                    delta["content"] = (delta.get("content") or "") + rest

        kind = event.get("type")
        if isinstance(kind, str) and kind.startswith("response."):
            if kind == "response.output_text.delta" and isinstance(event.get("delta"), str):
                key = (*base, "item", event.get("item_id"), event.get("content_index", 0))
                event["delta"] = self._restorer(key, session).feed(event["delta"])
            elif kind == "response.output_text.done" and isinstance(event.get("text"), str):
                self._end_stream(
                    (*base, "item", event.get("item_id"), event.get("content_index", 0))
                )
                event["text"] = session.restore(event["text"])
            elif kind == "response.content_part.done":
                _map_parts([event.get("part")], session.restore)
            elif kind == "response.output_item.done":
                _map_output_item(event.get("item"), session.restore)
            elif kind == "response.completed":
                for item in (event.get("response") or {}).get("output") or []:
                    _map_output_item(item, session.restore)
        return event

    # helpers

    def session_for(self, chat_id: str, user_id: str | None = None) -> PrivacySession | None:
        """The live session for a chat, if there is one."""
        return self._sessions.get((user_id or "", chat_id))

    def block_reason(self, protected: Protected) -> str:
        """The user-facing message for a blocked turn."""
        labels = sorted({f.label for f in protected.result.findings})
        parts = [self.block_message]
        if labels:
            parts.append("Detected: " + ", ".join(labels) + ".")
        if any("emergency" in g.lower() for g in protected.guidance):
            parts.append(EMERGENCY_HINT)
        parts.append("Remove those details and send the message again.")
        return " ".join(parts)

    def _protect_messages(self, session: PrivacySession, body: dict) -> Protected | None:
        session.spoken = self.spoken
        latest: Protected | None = None
        for message in body.get("messages") or []:
            if not isinstance(message, dict) or message.get("role") not in _TEXT_ROLES:
                continue
            is_user = message.get("role") == "user"
            results: list[Protected] = []

            def protect(
                text: str, _results: list[Protected] = results, _user: bool = is_user
            ) -> str:
                if not _user:
                    # Replies come back with real values after restore; map those first.
                    text = session.reprotect(text)
                protected = session.protect(text)
                _results.append(protected)
                return protected.text

            _map_content(message, protect)
            if is_user and results:
                latest = max(results, key=lambda p: p.blocked)
        return latest

    def _session(
        self,
        body: dict,
        chat_id: str | None,
        user_id: str | None,
        metadata: dict | None,
        *,
        create: bool,
    ) -> tuple[tuple[str, str] | None, PrivacySession | None]:
        chat = chat_id or (metadata or {}).get("chat_id") or body.get("chat_id")
        if not chat:
            chat = (body.get("metadata") or {}).get("chat_id")
        if not chat:
            # Direct API calls have no chat id: one session per request, carried
            # from inlet to stream/outlet by a token in the live metadata dict.
            if metadata is None:
                return None, (PrivacySession(spoken=self.spoken) if create else None)
            token = metadata.get(_SESSION_TOKEN_KEY)
            if not token:
                if not create:
                    return None, None
                token = metadata[_SESSION_TOKEN_KEY] = "request:" + uuid.uuid4().hex
            chat = token
        key = (user_id or "", str(chat))
        session = self._sessions.get(key)
        if session is None:
            if not create:
                return key, None
            session = self._sessions[key] = PrivacySession(spoken=self.spoken)
            while len(self._sessions) > self.max_chats:
                self._sessions.popitem(last=False)
        else:
            self._sessions.move_to_end(key)
        return key, session

    def _restorer(self, key: tuple[Any, ...], session: PrivacySession) -> StreamRestorer:
        restorer = self._streams.get(key)
        if restorer is None:
            restorer = self._streams[key] = session.stream()
            while len(self._streams) > self.max_chats:
                self._streams.popitem(last=False)
        return restorer

    def _end_stream(self, key: tuple[Any, ...]) -> str:
        restorer = self._streams.pop(key, None)
        return restorer.flush() if restorer else ""


def _map_content(message: dict, fn) -> None:
    content = message.get("content")
    if isinstance(content, str):
        message["content"] = fn(content)
    elif isinstance(content, list):
        _map_parts(content, fn)


def _map_parts(parts: list, fn) -> None:
    for part in parts:
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            part["text"] = fn(part["text"])


def _map_output_item(item: Any, fn) -> None:
    if isinstance(item, dict) and item.get("type") == "message":
        _map_parts(item.get("content") or [], fn)


try:
    from pydantic import BaseModel, Field
except ImportError:  # pragma: no cover - Open WebUI always ships pydantic
    BaseModel = None  # type: ignore[assignment,misc]

if BaseModel is not None:

    class Filter:
        """Open WebUI Filter Function backed by ``VoiceSafeOpenWebUI``."""

        class Valves(BaseModel):
            priority: int = Field(
                default=0,
                description="Filter order. Lower runs first; keep it below filters that log.",
            )
            spoken: bool = Field(
                default=True,
                description="Also catch personal data said out loud ('four two four two ...').",
            )
            block_on_critical: bool = Field(
                default=True,
                description="Stop the turn when the newest message holds a government ID, "
                "card security code or an emergency.",
            )
            restore_in_output: bool = Field(
                default=True,
                description="Show the real values in the reply on the user's own screen.",
            )
            max_chats: int = Field(
                default=200,
                description="How many chats' placeholder maps to keep in memory.",
            )

        def __init__(self) -> None:
            self.valves = self.Valves()
            self.core = VoiceSafeOpenWebUI()

        def _sync(self) -> VoiceSafeOpenWebUI:
            core, valves = self.core, self.valves
            core.spoken = valves.spoken
            core.block_on_critical = valves.block_on_critical
            core.restore_in_output = valves.restore_in_output
            core.max_chats = max(1, valves.max_chats)
            return core

        async def inlet(
            self,
            body: dict,
            __user__: dict | None = None,
            __metadata__: dict | None = None,
            __chat_id__: str | None = None,
        ) -> dict:
            try:
                return self._sync().inlet(
                    body,
                    chat_id=__chat_id__,
                    user_id=(__user__ or {}).get("id"),
                    metadata=__metadata__,
                )
            except ValueError as exc:
                # Open WebUI aborts the turn and shows this text in the chat.
                raise Exception(str(exc)) from None

        async def request(
            self,
            body: dict,
            __user__: dict | None = None,
            __metadata__: dict | None = None,
            __chat_id__: str | None = None,
        ) -> dict:
            return self._sync().request(
                body,
                chat_id=__chat_id__,
                user_id=(__user__ or {}).get("id"),
                metadata=__metadata__,
            )

        async def stream(
            self,
            event: dict,
            __user__: dict | None = None,
            __metadata__: dict | None = None,
            __chat_id__: str | None = None,
            __message_id__: str | None = None,
        ) -> dict:
            try:
                return self._sync().stream(
                    event,
                    chat_id=__chat_id__,
                    message_id=__message_id__,
                    user_id=(__user__ or {}).get("id"),
                    metadata=__metadata__,
                )
            except Exception:
                return event  # raising here would drop the whole event

        async def outlet(
            self,
            body: dict,
            __user__: dict | None = None,
            __metadata__: dict | None = None,
        ) -> dict:
            return self._sync().outlet(
                body,
                chat_id=body.get("chat_id"),
                user_id=(__user__ or {}).get("id"),
                metadata=__metadata__,
            )
