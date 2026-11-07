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
    # When the pattern has a named group "v", only that group is redacted.


# PII pattern rules

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
        kind="email",
        label="Email address",
        severity="medium",
        confidence=0.85,
        explanation=(
            "Speech-to-text often drops the 'at' in a spoken email "
            "('alex.rivera.gmail.com'). This still identifies a person."
        ),
        replacement="[email removed]",
        pattern=re.compile(
            r"\b(?!(?:www|mail|accounts|login|support|help)\.)[a-z0-9][a-z0-9_-]*"
            r"(?:\.[a-z0-9_-]+)*\.(?:gmail|googlemail|outlook|hotmail|live|yahoo|icloud|"
            r"proton|protonmail|aol|gmx)\.(?:com|co\.uk|me|net)\b",
            re.IGNORECASE,
        ),
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
        pattern=re.compile(r"\b(?:\d[ -]?){12,23}\d\b"),
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
            r"(?:the\s+)?(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4}"
            r"|\d{4}[-/]\d{1,2}[-/]\d{1,2}"
            r"|(?:january|february|march|april|may|june|july|august|september|october|november|december"
            r"|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s*\d{4}"
            r"|\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:january|february|march|april|may|june|july|august|september|october|november|december"
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
            "Passwords, partial passwords, tokens and secrets are highly sensitive. "
            "Never include them in text sent to a model."
        ),
        replacement="[secret removed]",
        pattern=re.compile(
            r"\b(?:"
            # "password is X", "password for my bank was X", "passcode: X"
            r"(?:password|passcode|passphrase)(?:\s+(?:for|to|on)\s+(?:my\s+|the\s+)?[\w.-]+){0,2}"
            r"\s*(?:is|was|might be|may be|could be|=|:)"
            r"\s*(?:something like|around|maybe|possibly)?\s*[^\s,.;]{4,}|"
            # "password BlueFalcon2026" with no verb: the value must look like a credential
            r"(?:password|passcode)\s+(?:something like\s+)?"
            r"(?=[^\s,.;]*[\d!@#$%^&*])[^\s,.;]{4,}|"
            # "api key is sk-123", "token: abc_123" (value must look like a key)
            r"(?:api key|access token|auth token|token|secret key|secret)\s*(?:is|was|=|:)"
            r"\s*(?=[^\s,.;]*[\d_\-!@#$%^&*])[^\s,.;]{4,}"
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
    PatternRule(
        kind="ssn",
        label="Social Security Number",
        severity="critical",
        confidence=0.9,
        explanation=(
            "A nine-digit number said right after 'social security' or 'SSN'. "
            "Spoken SSNs rarely include dashes. Never transmit them."
        ),
        replacement="[SSN removed]",
        pattern=re.compile(
            r"\b(?:ssn|social security(?:\s+number)?|social)(?:\b|(?=\d))[^.!?\n\d]{0,25}?"
            r"(?P<v>(?!000|666|9\d{2})\d{3}[-\s]?\d{2}[-\s]?\d{4})\b",
            re.IGNORECASE,
        ),
    ),
    PatternRule(
        kind="pin",
        label="PIN",
        severity="high",
        confidence=0.9,
        explanation="PINs unlock cards, phones and accounts. Never send them to a model.",
        replacement="[PIN removed]",
        pattern=re.compile(
            r"\b(?:pin|fin)(?:\s+(?:number|code))?\s*(?:is|was|=|:)?\s*(?P<v>\d(?:[ -]?\d){3,7})\b",
            re.IGNORECASE,
        ),
    ),
    PatternRule(
        kind="otp",
        label="One-time or verification code",
        severity="high",
        confidence=0.9,
        explanation=(
            "Verification and one-time codes are live credentials. Reading one out "
            "is the classic step in an account-takeover scam."
        ),
        replacement="[verification code removed]",
        pattern=re.compile(
            r"\b(?:(?:verification|one[- ]time|login|log-in|sign[- ]in|auth(?:entication)?|"
            r"2fa|two[- ]factor|sms|text|access)\s+code|otp|"
            r"code\s+(?:you|they|the bank|it)\s+(?:just\s+)?(?:sent|texted|gave)(?:\s+me)?)"
            r"\s*(?:is|was|=|:)?\s*(?P<v>\d(?:[ ,-]{0,2}\d){3,7})\b",
            re.IGNORECASE,
        ),
    ),
    PatternRule(
        kind="passport",
        label="Passport number",
        severity="critical",
        confidence=0.85,
        explanation="Passport numbers are government identity documents. Never transmit them.",
        replacement="[passport number removed]",
        pattern=re.compile(
            r"\bpassport(?:\s+(?:number|no\.?))?\s*(?:is|was|=|:)?\s*"
            r"(?P<v>(?=[A-Z0-9 ]*\d)[A-Z0-9](?:[A-Z0-9]|(?<=\d) (?=\d)){5,10})\b",
            re.IGNORECASE,
        ),
    ),
    PatternRule(
        kind="national_insurance",
        label="UK National Insurance number",
        severity="critical",
        confidence=0.9,
        explanation=(
            "National Insurance numbers are UK government identifiers. Never transmit them."
        ),
        replacement="[NI number removed]",
        pattern=re.compile(
            r"\b(?!BG|GB|NK|KN|TN|NT|ZZ)[A-CEGHJ-PR-TW-Z][A-CEGHJ-NPR-TW-Z]"
            r"\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b",
            re.IGNORECASE,
        ),
    ),
    PatternRule(
        kind="api_key",
        label="API key or access token",
        severity="high",
        confidence=0.97,
        explanation="This matches a known API key format. Revoke it if it was shared.",
        replacement="[API key removed]",
        pattern=re.compile(
            r"\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36}|"
            r"xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{35})\b"
        ),
    ),
    PatternRule(
        kind="person_name",
        label="Person name",
        severity="medium",
        confidence=0.8,
        explanation="The speaker introduced themselves by name. Names identify people.",
        replacement="[name removed]",
        pattern=re.compile(
            r"(?i:\bmy\s+name\s+is|\bmy\s+name's|\bthe\s+name's|\bthe\s+name\s+is)\s+"
            r"(?P<v>[A-Z][a-z]+(?:[ -](?!And\b|I\b)[A-Z][a-z'-]+){0,2})"
        ),
    ),
    PatternRule(
        kind="postcode",
        label="UK postcode",
        severity="medium",
        confidence=0.75,
        explanation="Postcodes narrow a location down to a handful of homes.",
        replacement="[postcode removed]",
        pattern=re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b"),
    ),
)


# Intent and context rules

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
            r"\b(?:lawsuit|(?:to|will|i'll|can i|should i|gonna|going to)\s+(?P<v>sue)|suing|"
            r"contract dispute|eviction|immigration|legal advice|"
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
            r"kill myself|call 911|call 999|call 112|call an ambulance|suicidal|"
            r"emergency(?!\s+(?:fund|funds|savings|contact|contacts|exit|kit|plan|brake|"
            r"number|services number|meeting|landing|lighting|power|stop)))\b",
            re.IGNORECASE,
        ),
        single_match=True,
    ),
)
