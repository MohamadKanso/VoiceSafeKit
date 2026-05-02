from voicesafekit.integrations.openvoiceos import protect_utterance


def test_openvoiceos_adapter_returns_safe_transcript() -> None:
    result = protect_utterance(
        "Please reset my account. My email is mo@example.com and my password is hunter2."
    )

    assert result.decision == "REVIEW"
    assert result.should_continue is True
    assert result.should_review is True
    assert result.safe_transcript == (
        "Please reset my account. My email is [email removed] and my [secret removed]."
    )
    assert result.findings == ("Email address", "Password or secret")


def test_openvoiceos_adapter_blocks_emergency_language() -> None:
    result = protect_utterance("I cannot breathe and this is an emergency.")

    assert result.decision == "BLOCK"
    assert result.should_continue is False
    assert result.should_review is True
    assert "Emergency or immediate harm" in result.findings
