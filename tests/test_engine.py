from voicesafekit.engine import analyze_transcript


def test_redacts_email_phone_and_secret() -> None:
    result = analyze_transcript(
        "My email is mo@example.com, my phone is +44 7340 166932, "
        "and my password is hunter2."
    )

    assert result.decision == "REVIEW"
    assert "[email removed]" in result.safe_transcript
    assert "[phone removed]" in result.safe_transcript
    assert "[secret removed]" in result.safe_transcript
    assert len(result.findings) == 3


def test_blocks_emergency_language() -> None:
    result = analyze_transcript("I can't breathe and this feels like an emergency.")

    assert result.decision == "BLOCK"
    assert any(finding.kind == "emergency" for finding in result.findings)
    assert "emergency help" in " ".join(result.assistant_guidance)


def test_safe_transcript_stays_safe() -> None:
    result = analyze_transcript("Set a timer for ten minutes and remind me to stretch.")

    assert result.decision == "SAFE"
    assert result.score == 0
    assert result.safe_transcript == "Set a timer for ten minutes and remind me to stretch."


def test_card_number_uses_luhn_check() -> None:
    result = analyze_transcript("Use card 4242 4242 4242 4242 for this order.")

    assert result.decision == "REVIEW"
    assert "[payment number removed]" in result.safe_transcript
    assert "[phone removed]" not in result.safe_transcript
    assert [finding.kind for finding in result.findings] == ["payment_card"]


def test_card_context_prevents_phone_false_positive() -> None:
    result = analyze_transcript("My card number is 1234 5678 1234 5678.")

    assert result.decision == "REVIEW"
    assert "[payment number removed]" in result.safe_transcript
    assert "[phone removed]" not in result.safe_transcript
    assert [finding.kind for finding in result.findings] == ["payment_card"]
