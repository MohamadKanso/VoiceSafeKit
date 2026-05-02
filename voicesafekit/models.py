from __future__ import annotations

from dataclasses import asdict, dataclass


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

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["findings"] = [finding.to_dict() for finding in self.findings]
        return payload

