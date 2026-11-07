from voicesafekit import PrivacySession


def test_protect_replaces_pii_with_numbered_placeholders() -> None:
    session = PrivacySession()
    protected = session.protect(
        "My name is Alex Rivera, email me at alex dot rivera at gmail dot com."
    )
    assert protected.text == "My name is [NAME_1], email me at [EMAIL_1]."
    assert protected.decision == "REDACT"
    assert not protected.blocked


def test_restore_puts_real_values_back() -> None:
    session = PrivacySession()
    session.protect("Email me at alex@example.com or bob@example.com.")
    assert session.restore("Sent to [EMAIL_1] and [EMAIL_2].") == (
        "Sent to alex@example.com and bob@example.com."
    )


def test_same_value_reuses_placeholder_across_turns_and_forms() -> None:
    session = PrivacySession()
    first = session.protect("my email is alex dot rivera at gmail dot com")
    second = session.protect("yes, alex.rivera@gmail.com")
    assert first.placeholders[0][0] == second.placeholders[0][0] == "[EMAIL_1]"


def test_credentials_are_never_restorable() -> None:
    session = PrivacySession()
    protected = session.protect("my password is BlueFalcon2026 and my pin is 4821")
    assert "BlueFalcon2026" not in protected.text
    assert "4821" not in protected.text
    assert session.restore("[SECRET_1] [PIN_1]") == "[SECRET_1] [PIN_1]"
    assert all("BlueFalcon2026" not in v for v in session.mapping.values())


def test_safety_intents_stay_in_text_but_set_decision() -> None:
    session = PrivacySession()
    protected = session.protect("I can't breathe, my email is a@b.co")
    assert "can't breathe" in protected.text
    assert protected.blocked
    assert any("emergency" in g for g in protected.guidance)


def test_stream_restorer_handles_split_placeholders() -> None:
    session = PrivacySession()
    session.protect("My name is Alex Rivera.")
    stream = session.stream()
    chunks = ["Hello [NA", "ME", "_1], how", " can I help? [", "unknown"]
    out = "".join(stream.feed(c) for c in chunks) + stream.flush()
    assert out == "Hello Alex Rivera, how can I help? [unknown"


def test_clear_forgets_values() -> None:
    session = PrivacySession()
    session.protect("email a@b.co")
    session.clear()
    assert session.restore("[EMAIL_1]") == "[EMAIL_1]"
