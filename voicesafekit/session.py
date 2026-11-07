"""Reversible redaction for LLM pipelines.

``PrivacySession`` swaps personal data for numbered placeholders before text goes
to a model, then puts the real values back into the model's reply:

    session = PrivacySession()
    safe = session.protect("Email me at alex dot rivera at gmail dot com")
    safe.text                     # "Email me at [EMAIL_1]"
    reply = llm(safe.text)        # "Sure, I'll send it to [EMAIL_1]."
    session.restore(reply)        # "Sure, I'll send it to alex dot rivera at gmail dot com."

The same value always gets the same placeholder for the life of the session, so
multi-turn conversations stay coherent. The mapping lives only in memory.

Credentials (passwords, PINs, CVVs, one-time codes, API keys) are never stored,
so they can never be restored into a reply or spoken back by a TTS voice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from voicesafekit.engine import analyze_transcript
from voicesafekit.models import AnalysisResult, Finding
from voicesafekit.rules import INTENT_RULES
from voicesafekit.spoken import normalize_spoken

PLACEHOLDER_TAGS: dict[str, str] = {
    "email": "EMAIL",
    "phone": "PHONE",
    "payment_card": "CARD",
    "payment_card_partial": "CARD_LAST4",
    "ssn": "SSN",
    "iban": "IBAN",
    "cvv": "CVV",
    "dob": "DOB",
    "ip_address": "IP",
    "secret": "SECRET",
    "address": "ADDRESS",
    "pin": "PIN",
    "otp": "OTP",
    "passport": "PASSPORT",
    "national_insurance": "NI_NUMBER",
    "api_key": "API_KEY",
    "person_name": "NAME",
    "postcode": "POSTCODE",
}

# Never kept in memory, never restored into model output.
NEVER_RESTORE = frozenset({"secret", "cvv", "pin", "otp", "api_key"})

INTENT_KINDS = frozenset(rule.kind for rule in INTENT_RULES)

_PLACEHOLDER = re.compile(r"\[([A-Z][A-Z0-9_]*?_\d+)\]")


@dataclass(frozen=True)
class Protected:
    """The result of ``PrivacySession.protect``."""

    text: str
    """Text safe to send to a model, with placeholders in place of personal data."""
    original: str
    result: AnalysisResult
    placeholders: tuple[tuple[str, str], ...]
    """(placeholder, kind) pairs created or reused for this text."""

    @property
    def decision(self) -> str:
        return self.result.decision

    @property
    def blocked(self) -> bool:
        return self.result.decision == "BLOCK"

    @property
    def guidance(self) -> tuple[str, ...]:
        return self.result.assistant_guidance


class PrivacySession:
    """Consistent, reversible placeholders across a whole conversation."""

    def __init__(self, *, spoken: bool = True, restore_credentials: bool = False) -> None:
        self.spoken = spoken
        self._never_restore = frozenset() if restore_credentials else NEVER_RESTORE
        self._values: dict[str, str] = {}  # placeholder -> original text
        self._by_key: dict[tuple[str, str], str] = {}  # (kind, canonical) -> placeholder
        self._counters: dict[str, int] = {}

    # public API

    def protect(self, text: str) -> Protected:
        """Analyse ``text`` and replace personal data with placeholders.

        Safety intents (medical, emergency, distress ...) are reported in
        ``result`` but left in the text, because the model needs them to respond
        well. Check ``Protected.blocked`` before forwarding.
        """
        result = analyze_transcript(text, spoken=self.spoken)
        pii = [f for f in result.findings if f.kind not in INTENT_KINDS]
        chunks: list[str] = []
        used: list[tuple[str, str]] = []
        cursor = 0
        for finding in sorted(pii, key=lambda f: f.start):
            placeholder = self._placeholder_for(finding, text[finding.start : finding.end])
            chunks.append(text[cursor : finding.start])
            chunks.append(placeholder)
            used.append((placeholder, finding.kind))
            cursor = finding.end
        chunks.append(text[cursor:])
        return Protected(
            text="".join(chunks),
            original=text,
            result=result,
            placeholders=tuple(used),
        )

    def restore(self, text: str) -> str:
        """Put real values back into model output. Unknown placeholders are kept."""
        return _PLACEHOLDER.sub(lambda m: self._values.get(m.group(1), m.group(0)), text)

    def reprotect(self, text: str) -> str:
        """Swap known real values back to their placeholders.

        Use this on anything that will be fed back to the model, such as the
        assistant's own spoken reply after ``restore``.
        """
        for name, value in sorted(self._values.items(), key=lambda kv: -len(kv[1])):
            text = text.replace(value, f"[{name}]")
        return text

    def stream(self) -> StreamRestorer:
        """A restorer for streamed model output (token by token)."""
        return StreamRestorer(self)

    @property
    def mapping(self) -> dict[str, str]:
        """A copy of the in-memory placeholder map (credentials are never in it)."""
        return {f"[{k}]": v for k, v in self._values.items()}

    def clear(self) -> None:
        """Forget every stored value."""
        self._values.clear()
        self._by_key.clear()
        self._counters.clear()

    # internals

    def _placeholder_for(self, finding: Finding, original: str) -> str:
        tag = PLACEHOLDER_TAGS.get(finding.kind, finding.kind.upper())
        key = (finding.kind, _canonical(original))
        existing = self._by_key.get(key)
        if existing:
            return f"[{existing}]"
        self._counters[tag] = self._counters.get(tag, 0) + 1
        name = f"{tag}_{self._counters[tag]}"
        self._by_key[key] = name
        if finding.kind not in self._never_restore:
            self._values[name] = original
        return f"[{name}]"


class StreamRestorer:
    """Restore placeholders in streamed text without splitting one across chunks."""

    _MAX_PLACEHOLDER = 32

    def __init__(self, session: PrivacySession) -> None:
        self._session = session
        self._buffer = ""

    def feed(self, chunk: str) -> str:
        """Add a chunk and return whatever text is now safe to emit."""
        self._buffer += chunk
        cut = self._buffer.rfind("[")
        if cut != -1 and "]" not in self._buffer[cut:]:
            tail = self._buffer[cut:]
            if len(tail) <= self._MAX_PLACEHOLDER and re.fullmatch(r"\[[A-Z0-9_]*", tail):
                ready, self._buffer = self._buffer[:cut], tail
                return self._session.restore(ready)
        ready, self._buffer = self._buffer, ""
        return self._session.restore(ready)

    def flush(self) -> str:
        """Return anything still held back (call at the end of a response)."""
        ready, self._buffer = self._buffer, ""
        return self._session.restore(ready)


def _canonical(value: str) -> str:
    written = normalize_spoken(value).text
    return re.sub(r"[\s().-]", "", written).lower()
