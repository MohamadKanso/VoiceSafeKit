from __future__ import annotations

from dataclasses import dataclass

from voicesafekit.engine import analyze_transcript


@dataclass(frozen=True)
class OpenVoiceOSSafetyResult:
    """A plain response shape for an OpenVoiceOS-style voice pipeline."""

    original_transcript: str
    safe_transcript: str
    decision: str
    risk_score: int
    assistant_guidance: tuple[str, ...]
    should_continue: bool
    should_review: bool
    findings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "original_transcript": self.original_transcript,
            "safe_transcript": self.safe_transcript,
            "decision": self.decision,
            "risk_score": self.risk_score,
            "assistant_guidance": list(self.assistant_guidance),
            "should_continue": self.should_continue,
            "should_review": self.should_review,
            "findings": list(self.findings),
        }


def protect_utterance(transcript: str) -> OpenVoiceOSSafetyResult:
    """Check a voice transcript before an assistant skill or LLM receives it.

    In a real OpenVoiceOS skill, call this after speech-to-text creates a transcript
    and before the text is passed to a downstream assistant action.
    """

    analysis = analyze_transcript(transcript)
    return OpenVoiceOSSafetyResult(
        original_transcript=transcript,
        safe_transcript=analysis.safe_transcript,
        decision=analysis.decision,
        risk_score=analysis.score,
        assistant_guidance=analysis.assistant_guidance,
        should_continue=analysis.decision != "BLOCK",
        should_review=analysis.decision in {"REVIEW", "BLOCK"},
        findings=tuple(finding.label for finding in analysis.findings),
    )

