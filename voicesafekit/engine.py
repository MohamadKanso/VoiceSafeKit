from __future__ import annotations

from voicesafekit.models import AnalysisResult, Finding
from voicesafekit.rules import INTENT_RULES, PATTERN_RULES, PatternRule

SEVERITY_POINTS = {
    "low": 10,
    "medium": 22,
    "high": 36,
    "critical": 55,
}
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def analyze_transcript(transcript: str) -> AnalysisResult:
    """Find privacy and safety risks in a voice assistant transcript."""

    findings = _find_risks(transcript)
    score = min(100, sum(SEVERITY_POINTS[finding.severity] for finding in findings))
    decision = _decision(score, findings)
    safe_transcript = _redact(transcript, findings)
    summary = _summary(decision, findings)
    guidance = _guidance(findings)
    return AnalysisResult(
        decision=decision,
        score=score,
        summary=summary,
        findings=tuple(findings),
        safe_transcript=safe_transcript,
        assistant_guidance=tuple(guidance),
    )


def _find_risks(transcript: str) -> list[Finding]:
    findings: list[Finding] = []
    for rule in (*PATTERN_RULES, *INTENT_RULES):
        findings.extend(_matches_for_rule(transcript, rule))
    return _remove_overlaps(sorted(findings, key=lambda finding: (finding.start, -finding.end)))


def _matches_for_rule(transcript: str, rule: PatternRule) -> list[Finding]:
    matches: list[Finding] = []
    for match in rule.pattern.finditer(transcript):
        matched_text = match.group(0).strip()
        if rule.kind == "phone" and _looks_like_card_shaped_number(
            matched_text,
            transcript,
            match.start(),
            match.end(),
        ):
            continue
        if rule.kind == "payment_card" and not _looks_like_payment_card(
            matched_text,
            transcript,
            match.start(),
            match.end(),
        ):
            continue
        matches.append(
            Finding(
                kind=rule.kind,
                label=rule.label,
                severity=rule.severity,
                explanation=rule.explanation,
                start=match.start(),
                end=match.end(),
                replacement=rule.replacement,
            )
        )
        if rule.single_match:
            break
    return matches


def _remove_overlaps(findings: list[Finding]) -> list[Finding]:
    accepted: list[Finding] = []
    occupied: list[range] = []
    priority_sorted = sorted(
        findings,
        key=lambda finding: (
            -SEVERITY_RANK[finding.severity],
            finding.start,
            -(finding.end - finding.start),
        ),
    )
    for finding in priority_sorted:
        span = range(finding.start, finding.end)
        if any(_ranges_overlap(span, used) for used in occupied):
            continue
        accepted.append(finding)
        occupied.append(span)
    return sorted(accepted, key=lambda finding: finding.start)


def _ranges_overlap(left: range, right: range) -> bool:
    return left.start < right.stop and right.start < left.stop


def _redact(transcript: str, findings: list[Finding]) -> str:
    if not findings:
        return transcript.strip()
    chunks: list[str] = []
    cursor = 0
    for finding in sorted(findings, key=lambda item: item.start):
        chunks.append(transcript[cursor : finding.start])
        chunks.append(finding.replacement)
        cursor = finding.end
    chunks.append(transcript[cursor:])
    return " ".join("".join(chunks).split())


def _decision(score: int, findings: list[Finding]) -> str:
    if any(finding.severity == "critical" for finding in findings):
        return "BLOCK"
    if score >= 55 or any(finding.severity == "high" for finding in findings):
        return "REVIEW"
    if score >= 22:
        return "REDACT"
    return "SAFE"


def _summary(decision: str, findings: list[Finding]) -> str:
    if not findings:
        return "No obvious privacy or safety risks were found."
    labels = sorted({finding.label for finding in findings})
    joined = ", ".join(labels)
    if decision == "BLOCK":
        return f"Do not send this directly to an LLM. Found: {joined}."
    if decision == "REVIEW":
        return f"Review before sending. Found: {joined}."
    return f"Redact the sensitive parts first. Found: {joined}."


def _guidance(findings: list[Finding]) -> list[str]:
    if not findings:
        return ["Proceed normally, but keep the user's data local whenever possible."]

    guidance = [
        "Remove or mask private details before sending the transcript to an LLM.",
        "Explain the limitation to the user in plain language.",
    ]
    kinds = {finding.kind for finding in findings}
    if "emergency" in kinds:
        guidance.insert(
            0,
            "For urgent safety issues, guide the user to emergency help immediately.",
        )
    if {"medical", "legal", "financial"} & kinds:
        guidance.append("Give general information only and suggest a qualified professional.")
    if {"payment_card", "secret"} & kinds:
        guidance.append("Never echo passwords, tokens, or payment details back to the user.")
    return guidance


def _looks_like_payment_card(value: str, transcript: str, start: int, end: int) -> bool:
    digits = [char for char in value if char.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    return _passes_luhn(value) or _has_card_context(transcript, start, end)


def _looks_like_card_shaped_number(value: str, transcript: str, start: int, end: int) -> bool:
    digits = [char for char in value if char.isdigit()]
    if len(digits) < 13 or value.strip().startswith("+"):
        return False
    return len(digits) <= 19 or _has_card_context(transcript, start, end)


def _has_card_context(transcript: str, start: int, end: int) -> bool:
    window = transcript[max(0, start - 32) : min(len(transcript), end + 32)].lower()
    return any(
        phrase in window
        for phrase in (
            "card",
            "credit",
            "debit",
            "visa",
            "mastercard",
            "payment",
        )
    )


def _passes_luhn(value: str) -> bool:
    digits = [int(char) for char in value if char.isdigit()]
    if len(digits) < 13:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0
