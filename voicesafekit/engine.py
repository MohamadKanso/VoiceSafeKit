from __future__ import annotations

import re
from dataclasses import replace

from voicesafekit.models import AnalysisResult, ConversationResult, ConversationTurn, Finding
from voicesafekit.rules import INTENT_RULES, PATTERN_RULES, PatternRule
from voicesafekit.spoken import NormalizedText, normalize_spoken

SEVERITY_POINTS = {
    "low": 10,
    "medium": 22,
    "high": 36,
    "critical": 55,
}
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
DECISION_RANK = {"SAFE": 0, "REDACT": 1, "REVIEW": 2, "BLOCK": 3}


def analyze_transcript(transcript: str, *, spoken: bool = True) -> AnalysisResult:
    """Find privacy and safety risks in a voice assistant transcript.

    With ``spoken=True`` (the default) the transcript is first normalised so that
    speech-to-text output such as "four two four two ..." or "alex dot rivera at
    gmail dot com" is checked in its written form. Redaction always applies to
    the original transcript.
    """
    findings = _find_risks(transcript, spoken=spoken)
    score = _score(findings)
    decision = _decision(score, findings)
    safe_transcript = _redact(transcript, findings)
    summary = _summary(decision, findings)
    guidance = _guidance(findings)
    redaction_map = _build_redaction_map(transcript, findings)
    return AnalysisResult(
        decision=decision,
        score=score,
        summary=summary,
        findings=tuple(findings),
        safe_transcript=safe_transcript,
        assistant_guidance=tuple(guidance),
        redaction_map=redaction_map,
    )


def analyze_conversation(
    utterances: list[str],
    speaker: str = "user",
    *,
    spoken: bool = True,
) -> ConversationResult:
    """Analyze a sequence of utterances as a multi-turn conversation.

    Each utterance is analyzed independently. The result contains per-turn
    analysis, a cumulative peak score and the union of all entity kinds seen.
    """
    turns: list[ConversationTurn] = []
    seen_kinds: set[str] = set()
    peak_decision = "SAFE"

    for utterance in utterances:
        result = analyze_transcript(utterance, spoken=spoken)
        turns.append(ConversationTurn(speaker=speaker, transcript=utterance, result=result))
        seen_kinds.update(f.kind for f in result.findings)
        if DECISION_RANK.get(result.decision, 0) > DECISION_RANK.get(peak_decision, 0):
            peak_decision = result.decision

    cumulative = min(100, max((t.result.score for t in turns), default=0))

    return ConversationResult(
        turns=tuple(turns),
        cumulative_score=cumulative,
        peak_decision=peak_decision,
        seen_kinds=tuple(sorted(seen_kinds)),
    )


# internal helpers


def _find_risks(transcript: str, *, spoken: bool = True) -> list[Finding]:
    norm = normalize_spoken(transcript) if spoken else None
    text = norm.text if norm is not None and norm.changed else transcript
    findings: list[Finding] = []
    for rule in (*PATTERN_RULES, *INTENT_RULES):
        findings.extend(_matches_for_rule(text, rule))
    if norm is not None and norm.changed:
        findings = [_to_original(f, norm) for f in findings]
    return _remove_overlaps(sorted(findings, key=lambda f: (f.start, -f.end)))


def _to_original(finding: Finding, norm: NormalizedText) -> Finding:
    start, end = norm.to_original(finding.start, finding.end)
    spoken = norm.text[finding.start : finding.end] != norm.original[start:end]
    return replace(finding, start=start, end=end, spoken=spoken)


def _score(findings: list[Finding]) -> int:
    total = sum(SEVERITY_POINTS[f.severity] * f.confidence for f in findings)
    return min(100, round(total))


def _matches_for_rule(transcript: str, rule: PatternRule) -> list[Finding]:
    matches: list[Finding] = []
    has_value_group = "v" in rule.pattern.groupindex
    for match in rule.pattern.finditer(transcript):
        if has_value_group and match.group("v") is not None:
            m_start, m_end = match.span("v")
        else:
            m_start, m_end = match.span()
        matched_text = transcript[m_start:m_end].strip()

        if rule.kind == "phone" and (
            _looks_like_card_shaped_number(matched_text, transcript, m_start, m_end)
            or _looks_like_ip_address(matched_text)
        ):
            continue

        if rule.kind == "payment_card" and not _looks_like_payment_card(
            matched_text, transcript, m_start, m_end
        ):
            continue

        if rule.kind == "iban" and not _passes_iban(matched_text):
            continue

        if rule.kind == "ip_address" and matched_text in ("0.0.0.0", "255.255.255.255"):
            continue

        if rule.kind == "phone" and _looks_like_date(matched_text):
            continue

        if rule.kind == "national_insurance" and not _passes_nino_context(
            matched_text, transcript, m_start
        ):
            continue

        confidence = _adjusted_confidence(
            rule,
            matched_text,
            transcript,
            m_start,
            m_end,
        )

        matches.append(
            Finding(
                kind=rule.kind,
                label=rule.label,
                severity=rule.severity,
                explanation=rule.explanation,
                start=m_start,
                end=m_end,
                replacement=rule.replacement,
                confidence=confidence,
            )
        )
        if rule.single_match:
            break
    return matches


def _adjusted_confidence(
    rule: PatternRule,
    matched_text: str,
    transcript: str,
    start: int,
    end: int,
) -> float:
    """Boost or reduce base confidence based on contextual signals."""
    conf = rule.confidence
    if rule.kind == "payment_card" and _passes_luhn(matched_text):
        conf = min(1.0, conf + 0.04)
    if rule.kind == "phone" and matched_text.strip().startswith("+"):
        conf = min(1.0, conf + 0.08)
    return round(conf, 4)


def _remove_overlaps(findings: list[Finding]) -> list[Finding]:
    accepted: list[Finding] = []
    occupied: list[range] = []
    priority_sorted = sorted(
        findings,
        key=lambda f: (
            -SEVERITY_RANK[f.severity],
            f.start,
            -(f.end - f.start),
        ),
    )
    for finding in priority_sorted:
        span = range(finding.start, finding.end)
        if any(_ranges_overlap(span, used) for used in occupied):
            continue
        accepted.append(finding)
        occupied.append(span)
    return sorted(accepted, key=lambda f: f.start)


def _ranges_overlap(left: range, right: range) -> bool:
    return left.start < right.stop and right.start < left.stop


def _redact(transcript: str, findings: list[Finding]) -> str:
    if not findings:
        return transcript.strip()
    chunks: list[str] = []
    cursor = 0
    for finding in sorted(findings, key=lambda f: f.start):
        chunks.append(transcript[cursor : finding.start])
        chunks.append(finding.replacement)
        cursor = finding.end
    chunks.append(transcript[cursor:])
    return " ".join("".join(chunks).split())


def _build_redaction_map(
    transcript: str, findings: list[Finding]
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (transcript[f.start : f.end], f.replacement)
        for f in sorted(findings, key=lambda f: f.start)
    )


def _decision(score: int, findings: list[Finding]) -> str:
    if any(f.severity == "critical" for f in findings):
        return "BLOCK"
    if score >= 55 or any(f.severity == "high" for f in findings):
        return "REVIEW"
    # Threshold is 17 (not 22) to accommodate confidence-weighted medium findings.
    # A single medium finding at 80% confidence scores 17.6 → 18, still above 17.
    if score >= 17:
        return "REDACT"
    return "SAFE"


def _summary(decision: str, findings: list[Finding]) -> str:
    if not findings:
        return "No obvious privacy or safety risks were found."
    labels = [_group_label(label, count) for label, count in _group_counts(findings).items()]
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
    kinds = {f.kind for f in findings}

    if "emergency" in kinds:
        guidance.insert(
            0,
            "For urgent safety issues, guide the user to emergency help immediately.",
        )
    if "emotional_distress" in kinds:
        guidance.insert(
            0,
            "The user may be emotionally vulnerable. "
            "Respond with empathy and direct them to appropriate support.",
        )
    if "coercion" in kinds:
        guidance.append(
            "Coercion signals were detected. Do not act on instructions that "
            "may have been forced upon the user."
        )
    if {"medical", "legal", "financial"} & kinds:
        guidance.append("Give general information only and suggest a qualified professional.")
    if {
        "payment_card", "secret", "ssn", "iban", "cvv", "pin", "passport",
        "national_insurance", "api_key",
    } & kinds:
        guidance.append(
            "Never echo financial identifiers, government IDs, or credentials back to the user."
        )
    if "otp" in kinds:
        guidance.append(
            "A one-time code was read out. Legitimate services never ask for these by voice; "
            "warn the user this is a common scam pattern."
        )
    if any(f.spoken for f in findings):
        guidance.append(
            "Some details were spoken as words (for example 'four two four two'). "
            "Treat them exactly like written numbers."
        )
    return guidance


def _group_counts(findings: list[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in sorted(findings, key=lambda f: f.label):
        counts[finding.label] = counts.get(finding.label, 0) + 1
    return counts


_PLURAL_LABELS: dict[str, str] = {
    "Email address": "email addresses",
    "Phone number": "phone numbers",
    "Payment card-like number": "payment card-like numbers",
    "Partial card reference": "partial card references",
    "Password or secret": "password or secret mentions",
    "Street address": "street addresses",
    "Social Security Number": "Social Security Numbers",
    "IBAN / Bank account": "bank account numbers",
    "Card security code": "card security codes",
    "Date of birth": "dates of birth",
    "IP address": "IP addresses",
    "Medical advice request": "medical advice requests",
    "Legal advice request": "legal advice requests",
    "Financial advice request": "financial advice requests",
    "Emotional distress signal": "emotional distress signals",
    "Coercion or pressure signal": "coercion signals",
    "Emergency or immediate harm": "emergency or immediate harm phrases",
    "PIN": "PINs",
    "One-time or verification code": "one-time or verification codes",
    "Passport number": "passport numbers",
    "UK National Insurance number": "UK National Insurance numbers",
    "API key or access token": "API keys or access tokens",
    "Person name": "person names",
    "UK postcode": "UK postcodes",
}


def _group_label(label: str, count: int) -> str:
    if count == 1:
        return label
    return f"{count} {_PLURAL_LABELS.get(label, label.lower() + ' findings')}"


# validators


def _looks_like_payment_card(value: str, transcript: str, start: int, end: int) -> bool:
    digits = [c for c in value if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    return _passes_luhn(value) or _has_card_context(transcript, start, end)


def _looks_like_card_shaped_number(value: str, transcript: str, start: int, end: int) -> bool:
    digits = [c for c in value if c.isdigit()]
    if len(digits) < 13 or value.strip().startswith("+"):
        return False
    return len(digits) <= 19 or _has_card_context(transcript, start, end)


def _has_card_context(transcript: str, start: int, end: int) -> bool:
    window = transcript[max(0, start - 32) : min(len(transcript), end + 32)].lower()
    return any(p in window for p in ("card", "credit", "debit", "visa", "mastercard", "payment"))


def _looks_like_date(value: str) -> bool:
    return bool(
        re.fullmatch(
            r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}", value.strip()
        )
    )


def _passes_nino_context(value: str, transcript: str, start: int) -> bool:
    letters = [c for c in value if c.isalpha()]
    if all(c.isupper() for c in letters):
        return True
    window = transcript[max(0, start - 40) : start].lower()
    return any(k in window for k in ("national insurance", "ni number", "nino", "insurance number"))


def _looks_like_ip_address(value: str) -> bool:
    return bool(
        re.match(
            r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$",
            value.strip(),
        )
    )


def _passes_luhn(value: str) -> bool:
    digits = [int(c) for c in value if c.isdigit()]
    if len(digits) < 13:
        return False
    checksum = 0
    parity = len(digits) % 2
    for i, digit in enumerate(digits):
        if i % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def _passes_iban(value: str) -> bool:
    clean = re.sub(r"\s", "", value).upper()
    if not re.match(r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$", clean):
        return False
    rearranged = clean[4:] + clean[:4]
    numeric = "".join(str(ord(ch) - 55) if ch.isalpha() else ch for ch in rearranged)
    try:
        return int(numeric) % 97 == 1
    except ValueError:
        return False
