from voicesafekit.engine import analyze_conversation, analyze_transcript


# ─── existing detector tests ───────────────────────────────────────────────────


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
    assert any(f.kind == "emergency" for f in result.findings)
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
    assert [f.kind for f in result.findings] == ["payment_card"]


def test_card_context_prevents_phone_false_positive() -> None:
    result = analyze_transcript("My card number is 1234 5678 1234 5678.")
    assert result.decision == "REVIEW"
    assert "[payment number removed]" in result.safe_transcript
    assert "[phone removed]" not in result.safe_transcript
    assert [f.kind for f in result.findings] == ["payment_card"]


def test_summary_groups_repeated_email_findings() -> None:
    result = analyze_transcript(
        "My email is daniel.hughes@companymail.com and my backup email is "
        "dan.hughes92@gmail.com. My phone is +44 7911 234567."
    )
    assert result.decision == "REVIEW"
    assert "2 email addresses" in result.summary
    assert result.summary.count("Email address") == 0
    assert result.safe_transcript.count("[email removed]") == 2


def test_detects_partial_password_phrase() -> None:
    result = analyze_transcript(
        "I think my password was something like WinterSecure!2026 but I am not sure."
    )
    assert result.decision == "REVIEW"
    assert "[secret removed]" in result.safe_transcript
    assert any(f.kind == "secret" for f in result.findings)


def test_detects_partial_card_reference() -> None:
    result = analyze_transcript("My card ends in 4821 if that helps confirm it is me.")
    assert result.decision == "REDACT"
    assert "[partial card reference removed]" in result.safe_transcript
    assert any(f.kind == "payment_card_partial" for f in result.findings)


def test_long_account_recovery_transcript_flags_all_relevant_groups() -> None:
    transcript = (
        "Hi, I need help urgently. I am locked out of my work account. "
        "My email is daniel.hughes@companymail.com and my backup email is "
        "dan.hughes92@gmail.com. My phone number is +44 7911 234567. "
        "I also think my password was something like WinterSecure!2026 but I am not sure. "
        "I might have used the same password on my banking app. "
        "My card ends in 4821 if that helps confirm it is me."
    )
    result = analyze_transcript(transcript)
    kinds = {f.kind for f in result.findings}
    assert result.decision == "REVIEW"
    assert {"email", "phone", "secret", "payment_card_partial"} <= kinds
    assert "2 email addresses" in result.summary
    assert "[partial card reference removed]" in result.safe_transcript


# ─── new detector tests (v0.2.0) ──────────────────────────────────────────────


def test_detects_ssn() -> None:
    result = analyze_transcript(
        "My Social Security Number is 471-55-8843, please verify my identity."
    )
    assert result.decision == "BLOCK"
    assert any(f.kind == "ssn" for f in result.findings)
    assert "[SSN removed]" in result.safe_transcript


def test_ssn_confidence_is_high() -> None:
    result = analyze_transcript("My SSN is 471-55-8843.")
    ssn_finding = next((f for f in result.findings if f.kind == "ssn"), None)
    assert ssn_finding is not None
    assert ssn_finding.confidence >= 0.90


def test_detects_valid_iban() -> None:
    result = analyze_transcript(
        "Please transfer funds to GB29NWBK60161331926819 — that is my account."
    )
    assert result.decision == "BLOCK"
    assert any(f.kind == "iban" for f in result.findings)
    assert "[bank account removed]" in result.safe_transcript


def test_rejects_invalid_iban_checksum() -> None:
    result = analyze_transcript(
        "The reference number is GB29NWBK60161331926800 — just store it."
    )
    assert not any(f.kind == "iban" for f in result.findings)


def test_detects_cvv() -> None:
    result = analyze_transcript("The CVV on my card is 847, and the card ends in 4821.")
    assert result.decision == "BLOCK"
    assert any(f.kind == "cvv" for f in result.findings)
    assert "[security code removed]" in result.safe_transcript


def test_detects_date_of_birth() -> None:
    result = analyze_transcript("My date of birth is March 15, 1988.")
    assert any(f.kind == "dob" for f in result.findings)
    assert "[date of birth removed]" in result.safe_transcript


def test_detects_ip_address() -> None:
    result = analyze_transcript(
        "My device is at IP address 192.168.1.104 on the internal network."
    )
    assert any(f.kind == "ip_address" for f in result.findings)
    assert "[IP address removed]" in result.safe_transcript


def test_detects_emotional_distress() -> None:
    result = analyze_transcript(
        "I have been feeling really hopeless lately. I don't know what to do."
    )
    assert result.decision == "REVIEW"
    assert any(f.kind == "emotional_distress" for f in result.findings)
    assert "empathy" in " ".join(result.assistant_guidance).lower()


def test_detects_coercion_signal() -> None:
    result = analyze_transcript(
        "They made me say this. Please don't tell anyone I said this. "
        "I need to transfer the money or they will hurt me."
    )
    assert any(f.kind == "coercion" for f in result.findings)
    assert "coercion" in " ".join(result.assistant_guidance).lower()


def test_redaction_map_is_populated() -> None:
    result = analyze_transcript("My email is user@example.com and my phone is +44 7911 234567.")
    assert len(result.redaction_map) >= 2
    originals = [pair[0] for pair in result.redaction_map]
    replacements = [pair[1] for pair in result.redaction_map]
    assert any("@" in o for o in originals)
    assert "[email removed]" in replacements


def test_all_findings_have_confidence() -> None:
    result = analyze_transcript(
        "My email is mo@example.com, my SSN is 471-55-8843, "
        "and I can't breathe properly."
    )
    for finding in result.findings:
        assert 0.0 <= finding.confidence <= 1.0


def test_identity_theft_transcript_blocks() -> None:
    transcript = (
        "Hi, I need help. My Social Security Number is 471-55-8843. "
        "My bank account IBAN is GB29NWBK60161331926819. "
        "The CVV on my Visa card is 847. "
        "I was born on March 15, 1988. "
        "My device IP is 192.168.1.104."
    )
    result = analyze_transcript(transcript)
    kinds = {f.kind for f in result.findings}
    assert result.decision == "BLOCK"
    assert {"ssn", "iban", "cvv"} <= kinds
    assert result.score == 100


def test_analyze_conversation_tracks_peak_decision() -> None:
    utterances = [
        "Set a timer for ten minutes.",
        "My SSN is 471-55-8843 — I need to verify.",
        "Thank you, I think that is all.",
    ]
    result = analyze_conversation(utterances)
    assert result.peak_decision == "BLOCK"
    assert "ssn" in result.seen_kinds
    assert len(result.turns) == 3


def test_analyze_conversation_safe_conversation() -> None:
    utterances = [
        "Play some music.",
        "Set a reminder for tomorrow.",
    ]
    result = analyze_conversation(utterances)
    assert result.peak_decision == "SAFE"
    assert result.cumulative_score == 0
    assert len(result.seen_kinds) == 0


def test_conversation_serialization() -> None:
    result = analyze_conversation(["My email is x@y.com.", "Thanks."])
    payload = result.to_dict()
    assert "turns" in payload
    assert "cumulative_score" in payload
    assert "peak_decision" in payload
    assert len(payload["turns"]) == 2
