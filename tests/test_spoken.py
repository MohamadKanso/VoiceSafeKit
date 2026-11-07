import pytest

from voicesafekit import analyze_transcript, normalize_spoken

# The normaliser itself


@pytest.mark.parametrize(
    ("spoken", "written"),
    [
        ("four two four two four two four two", "42424242"),
        ("oh seven seven double oh nine", "077009"),
        ("plus four four seven seven double oh nine hundred one two three", "+447700900123"),
        ("triple five one two", "55512"),
        ("nineteen eighty three", "1983"),
        ("forty-two sixty nine", "4269"),
        ("alex dot rivera at gmail dot com", "alex.rivera@gmail.com"),
        ("j underscore smith at outlook dot co dot uk", "j_smith@outlook.co.uk"),
        ("march fourth", "march 4th"),
        ("twenty first of may", "21st of may"),
    ],
)
def test_normalises_spoken_forms(spoken: str, written: str) -> None:
    assert normalize_spoken(spoken).text == written


@pytest.mark.parametrize(
    "text",
    [
        "I have two kids and one dog.",
        "Oh no, that is fine.",
        "Set a timer for twenty five minutes.",
        "Meet me at home.",
        "I came first in the race.",
    ],
)
def test_ordinary_speech_is_untouched(text: str) -> None:
    assert normalize_spoken(text).text == text


def test_maps_spans_back_to_original_words() -> None:
    norm = normalize_spoken("my social is four seven one, five five, eight eight four three")
    start = norm.text.index("471")
    s, e = norm.to_original(start, len(norm.text))
    assert norm.original[s:e] == "four seven one, five five, eight eight four three"


# Spoken PII is detected and redacted in the original transcript


@pytest.mark.parametrize(
    ("transcript", "kind", "redacted"),
    [
        (
            "my card number is four two four two four two four two "
            "four two four two four two four two",
            "payment_card",
            "my card number is [payment number removed]",
        ),
        (
            "my social is four seven one five five eight eight four three",
            "ssn",
            "my social is [SSN removed]",
        ),
        (
            "my email is alex dot rivera at gmail dot com",
            "email",
            "my email is [email removed]",
        ),
        (
            "call me on oh seven seven zero zero nine double oh one two three",
            "phone",
            "call me on [phone removed]",
        ),
        ("my pin is four eight two one", "pin", "my pin is [PIN removed]"),
        (
            "the code they just texted me is four eight two nine one three",
            "otp",
            "the code they just texted me is [verification code removed]",
        ),
    ],
)
def test_detects_spoken_pii(transcript: str, kind: str, redacted: str) -> None:
    result = analyze_transcript(transcript)
    finding = next(f for f in result.findings if f.kind == kind)
    assert finding.spoken is True
    assert result.safe_transcript == redacted


def test_spoken_date_of_birth() -> None:
    result = analyze_transcript("I was born on march fourth nineteen eighty three.")
    assert any(f.kind == "dob" for f in result.findings)


def test_spoken_mode_can_be_disabled() -> None:
    result = analyze_transcript("my pin is four eight two one", spoken=False)
    assert result.findings == ()


def test_redaction_map_keeps_the_spoken_words() -> None:
    result = analyze_transcript("my pin is four eight two one")
    assert result.redaction_map == (("four eight two one", "[PIN removed]"),)


# False positives fixed in 0.5


@pytest.mark.parametrize(
    "text",
    [
        "I need to build an emergency fund this year.",
        "Remind me to call Sue about dinner.",
        "What is the secret ingredient in this recipe?",
        "Help me reset my password please.",
        "The password manager is great.",
        "The meeting is on 2026-11-07 at the office.",
        "How many tokens does the model use?",
    ],
)
def test_common_phrases_are_safe(text: str) -> None:
    result = analyze_transcript(text)
    assert result.decision == "SAFE", result.findings


# New detectors


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("My password for netflix is hunter22.", "secret"),
        ("My passport number is 123456789.", "passport"),
        ("My national insurance number is ab 12 34 56 c.", "national_insurance"),
        ("NI: AB123456C", "national_insurance"),
        ("My name is John Smith.", "person_name"),
        ("I live near NW1 6XE.", "postcode"),
        ("here is my key sk-proj-abcdefghijklmnopqrstuvwx1234", "api_key"),
        ("My SSN is 471558843.", "ssn"),
        ("I want to sue my landlord.", "legal"),
    ],
)
def test_new_detectors(text: str, kind: str) -> None:
    result = analyze_transcript(text)
    assert any(f.kind == kind for f in result.findings), result.findings


def test_value_only_redaction_keeps_context_words() -> None:
    result = analyze_transcript("My name is John Smith and my passport number is 123456789.")
    assert result.safe_transcript == (
        "My name is [name removed] and my passport number is [passport number removed]."
    )
