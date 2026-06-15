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
    confidence: float = 1.0
    single_match: bool = False


# ─── PII pattern rules ─────────────────────────────────────────────────────────

PATTERN_RULES: tuple[PatternRule, ...] = (
    PatternRule(
        kind="email",
        label="Email address",
        severity="medium",
        confidence=0.98,
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
        confidence=0.85,
        explanation="Phone numbers are personal data and should usually be redacted.",
        replacement="[phone removed]",
        pattern=re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d\b"),
    ),
    PatternRule(
        kind="payment_card",
        label="Payment card-like number",
        severity="high",
        confidence=0.95,
        explanation="This looks like a payment card number. Do not send it to an LLM.",
        replacement="[payment number removed]",
        pattern=re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
    ),
    PatternRule(
        kind="payment_card_partial",
        label="Partial card reference",
        severity="medium",
        confidence=0.92,
        explanation=(
            "Partial card details can still be used for identity checks. "
            "Remove them before sending text to a model."
        ),
        replacement="[partial card reference removed]",
        pattern=re.compile(
            r"\b(?:card|credit card|debit card)\s+"
            r"(?:(?:ends?|ending)\s+(?:in|with)|last\s+(?:4|four)(?:\s+digits)?(?:\s+(?:are|is))?)"
            r"\s+\d{4}\b",
            re.IGNORECASE,
        ),
    ),
    PatternRule(
        kind="ssn",
        label="Social Security Number",
        severity="critical",
        confidence=0.95,
        explanation=(
            "US Social Security Numbers are government-issued identity numbers. "
            "Exposure enables identity theft. Never transmit them."
        ),
        replacement="[SSN removed]",
        pattern=re.compile(
            r"\b(?!000|666|9\d{2})\d{3}[-\s]\d{2}[-\s]\d{4}\b"
        ),
    ),
    PatternRule(
        kind="iban",
        label="IBAN / Bank account",
        severity="critical",
        confidence=0.88,
        explanation=(
            "International Bank Account Numbers enable financial access. "
            "Do not transmit them to an LLM."
        ),
        replacement="[bank account removed]",
        pattern=re.compile(
            r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"
        ),
    ),
    PatternRule(
        kind="cvv",
        label="Card security code",
        severity="critical",
        confidence=0.93,
        explanation=(
            "CVV/CVC codes grant payment access alongside card numbers. "
            "Never transmit these."
        ),
        replacement="[security code removed]",
        # Allow up to 60 non-sentence chars between keyword and the 3-4 digit code.
        pattern=re.compile(
            r"\b(?:cvv|cvc|cv2|security code|card security code|card code)\b"
            r"[^.!?\n]{0,60}\b\d{3,4}\b",
            re.IGNORECASE,
        ),
    ),
    PatternRule(
        kind="dob",
        label="Date of birth",
        severity="medium",
        confidence=0.80,
        explanation=(
            "Dates of birth are used in identity verification. "
            "Redact unless the context makes transmission necessary."
        ),
        replacement="[date of birth removed]",
        pattern=re.compile(
            r"\b(?:born|dob|date of birth|d\.o\.b|birthday)\s*(?:is|was|on|:)?\s*"
            r"(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4}"
            r"|\d{4}[-/]\d{1,2}[-/]\d{1,2}"
            r"|(?:january|february|march|april|may|june|july|august|september|october|november|december"
            r"|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\.?\s+\d{1,2},?\s*\d{4}"
            r"|\d{1,2}\s+(?:january|february|march|april|may|june|july|august|september|october|november|december"
            r"|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\.?\s+\d{4})\b",
            re.IGNORECASE,
        ),
    ),
    PatternRule(
        kind="ip_address",
        label="IP address",
        severity="medium",
        confidence=0.88,
        explanation="IP addresses can reveal location or internal network topology.",
        replacement="[IP address removed]",
        pattern=re.compile(
            r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
        ),
    ),
    PatternRule(
        kind="secret",
        label="Password or secret",
        severity="high",
        confidence=0.88,
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
        confidence=0.80,
        explanation="Street addresses can reveal where someone lives or works.",
        replacement="[address removed]",
        pattern=re.compile(
            r"\b\d{1,5}\s+[A-Za-z]+(?:\s+[A-Za-z]+){0,3}\s+"
            r"(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Dr|Way|Close|Court)\b",
            re.IGNORECASE,
        ),
    ),
)


# ─── Intent and context rules ──────────────────────────────────────────────────

INTENT_RULES: tuple[PatternRule, ...] = (
    PatternRule(
        kind="medical",
        label="Medical advice request",
        severity="high",
        confidence=0.75,
        explanation=(
            "Medical questions should be handled carefully "
            "and should not replace a clinician."
        ),
        replacement="[medical details withheld]",
        pattern=re.compile(
            r"\b(?:chest pain|diagnose|dose|medication|symptoms|blood pressure|"
            r"antibiotic|panic attack|antidepressant|seizure|insulin)\b",
            re.IGNORECASE,
        ),
        single_match=True,
    ),
    PatternRule(
        kind="legal",
        label="Legal advice request",
        severity="high",
        confidence=0.75,
        explanation="Legal questions need careful boundaries and may require a professional.",
        replacement="[legal details withheld]",
        pattern=re.compile(
            r"\b(?:lawsuit|sue|contract dispute|eviction|immigration|legal advice|"
            r"restraining order|custody|divorce settlement)\b",
            re.IGNORECASE,
        ),
        single_match=True,
    ),
    PatternRule(
        kind="financial",
        label="Financial advice request",
        severity="high",
        confidence=0.75,
        explanation=(
            "Financial advice can affect someone's money "
            "and should be handled with caution."
        ),
        replacement="[financial details withheld]",
        pattern=re.compile(
            r"\b(?:invest all|stock tip|crypto|loan application|credit score|mortgage|"
            r"bankruptcy|day trading|options contract)\b",
            re.IGNORECASE,
        ),
        single_match=True,
    ),
    PatternRule(
        kind="emotional_distress",
        label="Emotional distress signal",
        severity="high",
        confidence=0.70,
        explanation=(
            "The user may be in emotional distress. Respond with care "
            "and refer to appropriate support resources."
        ),
        replacement="[emotional distress signal]",
        pattern=re.compile(
            r"\b(?:feel(?:ing)?(?:\s+\w+)?\s+hopeless|can't go on|don't see the point|"
            r"everything is pointless|nobody cares about me|"
            r"(?:i'm|i am)\s+worthless|want to disappear|hate myself|"
            r"can't take (?:this|it) anymore|feel like giving up|"
            r"don't want to be here anymore)\b",
            re.IGNORECASE,
        ),
        single_match=True,
    ),
    PatternRule(
        kind="coercion",
        label="Coercion or pressure signal",
        severity="high",
        confidence=0.65,
        explanation=(
            "The transcript may suggest the user is being pressured, "
            "manipulated, or coerced into sharing information."
        ),
        replacement="[coercion signal]",
        pattern=re.compile(
            r"\b(?:told me to say (?:this|that)|made me (?:say|do this)|"
            r"they forced me|don't tell anyone (?:i said|about) this|"
            r"keep this (?:between us|secret)|"
            r"they(?:'re| are) making me|if you don't help me|"
            r"or (?:they'll|they will) hurt)\b",
            re.IGNORECASE,
        ),
        single_match=True,
    ),
    PatternRule(
        kind="emergency",
        label="Emergency or immediate harm",
        severity="critical",
        confidence=0.90,
        explanation=(
            "The assistant should route urgent safety issues "
            "to emergency help, not improvise."
        ),
        replacement="[urgent safety details withheld]",
        pattern=re.compile(
            r"\b(?:can't breathe|cannot breathe|heart attack|overdose|hurt myself|"
            r"kill myself|call 911|call an ambulance|emergency|suicidal)\b",
            re.IGNORECASE,
        ),
        single_match=True,
    ),
)
