from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Finding:
    """One privacy or safety issue found in a transcript."""

    kind: str
    label: str
    severity: str
    explanation: str
    start: int
    end: int
    replacement: str
    confidence: float = 1.0  # 0.0–1.0 detection confidence

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AnalysisResult:
    """The full result returned by VoiceSafeKit."""

    decision: str
    score: int
    summary: str
    findings: tuple[Finding, ...]
    safe_transcript: str
    assistant_guidance: tuple[str, ...]
    redaction_map: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["findings"] = [f.to_dict() for f in self.findings]
        payload["redaction_map"] = [
            {"found": original, "replaced_with": replacement}
            for original, replacement in self.redaction_map
        ]
        return payload


@dataclass(frozen=True)
class ConversationTurn:
    """A single utterance in a multi-turn conversation."""

    speaker: str
    transcript: str
    result: AnalysisResult

    def to_dict(self) -> dict[str, object]:
        return {
            "speaker": self.speaker,
            "transcript": self.transcript,
            "result": self.result.to_dict(),
        }


@dataclass(frozen=True)
class ConversationResult:
    """The aggregated result of a multi-turn conversation analysis."""

    turns: tuple[ConversationTurn, ...]
    cumulative_score: int
    peak_decision: str
    seen_kinds: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "turns": [t.to_dict() for t in self.turns],
            "cumulative_score": self.cumulative_score,
            "peak_decision": self.peak_decision,
            "seen_kinds": list(self.seen_kinds),
        }
