from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PatternRule:
    kind: str
    label: str
    severity: str
    explanation: str
    replacement: str
    pattern: re.Pattern[str]
    single_match: bool = False


PATTERN_RULES: tuple[PatternRule, ...] = (
    PatternRule(
        kind="email",
        label="Email address",
        severity="medium",
        explanation=(
            "Email addresses can identify a person. "
            "Remove them before sending text to a model."
        ),
        replacement="[email removed]",
        pattern=re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"),
    ),
    PatternRule(
        kind="phone",
        label="Phone number",
        severity="medium",
        explanation="Phone numbers are personal data and should usually be redacted.",
        replacement="[phone removed]",
        pattern=re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d\b"),
    ),
    PatternRule(
        kind="payment_card",
        label="Payment card-like number",
        severity="high",
        explanation="This looks like a payment card number. Do not send it to an LLM.",
        replacement="[payment number removed]",
        pattern=re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
    ),
    PatternRule(
        kind="secret",
        label="Password or secret",
        severity="high",
        explanation=(
            "Passwords, partial passwords, tokens, and secrets are highly sensitive. "
            "Never include them in text sent to a model."
        ),
        replacement="[secret removed]",
        pattern=re.compile(
            r"\b(?:"
            r"(?:password|passcode)\s*(?:is|was|might be|may be|could be|=|:)?"
            r"\s*(?:something like|around|maybe|possibly)?\s*[^\s,.;]{4,}|"
            r"(?:api key|token|secret)\s*(?:is|was|=|:)?\s*[^\s,.;]{4,}"
            r")",
            re.IGNORECASE,
        ),
    ),
    PatternRule(
        kind="address",
        label="Street address",
        severity="medium",
        explanation="Street addresses can reveal where someone lives or works.",
        replacement="[address removed]",
        pattern=re.compile(
            r"\b\d{1,5}\s+[A-Za-z]+(?:\s+[A-Za-z]+){0,3}\s+"
            r"(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Dr|Way|Close|Court)\b",
            re.IGNORECASE,
        ),
    ),
)


INTENT_RULES: tuple[PatternRule, ...] = (
    PatternRule(
        kind="medical",
        label="Medical advice request",
        severity="high",
        explanation=(
            "Medical questions should be handled carefully "
            "and should not replace a clinician."
        ),
        replacement="[medical details withheld]",
        pattern=re.compile(
            r"\b(?:chest pain|diagnose|dose|medication|symptoms|blood pressure|"
            r"antibiotic|panic attack)\b",
            re.IGNORECASE,
        ),
        single_match=True,
    ),
    PatternRule(
        kind="legal",
        label="Legal advice request",
        severity="high",
        explanation="Legal questions need careful boundaries and may require a professional.",
        replacement="[legal details withheld]",
        pattern=re.compile(
            r"\b(?:lawsuit|sue|contract dispute|eviction|immigration|legal advice)\b",
            re.IGNORECASE,
        ),
        single_match=True,
    ),
    PatternRule(
        kind="financial",
        label="Financial advice request",
        severity="high",
        explanation=(
            "Financial advice can affect someone's money "
            "and should be handled with caution."
        ),
        replacement="[financial details withheld]",
        pattern=re.compile(
            r"\b(?:invest all|stock tip|crypto|loan application|credit score|mortgage)\b",
            re.IGNORECASE,
        ),
        single_match=True,
    ),
    PatternRule(
        kind="emergency",
        label="Emergency or immediate harm",
        severity="critical",
        explanation=(
            "The assistant should route urgent safety issues "
            "to emergency help, not improvise."
        ),
        replacement="[urgent safety details withheld]",
        pattern=re.compile(
            r"\b(?:can't breathe|cannot breathe|heart attack|overdose|hurt myself|"
            r"kill myself|emergency)\b",
            re.IGNORECASE,
        ),
        single_match=True,
    ),
)
