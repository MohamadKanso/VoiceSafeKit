# Changelog

This file records the visible phases of VoiceSafeKit so the project history is
easy to follow.

## Phase 0.3 — Intelligence and Context (3 June 2026)

A significant capability upgrade informed by research into production voice AI
safety systems and the Sesame AI conversational speech model work on contextual
presence in voice interfaces.

### New detectors (Python + browser)

- **Social Security Number** (critical, 95% confidence) — pattern + invalid-range filter.
- **IBAN / Bank account** (critical, 88% confidence) — pattern + mod-97 checksum validation.
- **Card security code / CVV** (critical, 93% confidence) — keyword-triggered exact match.
- **Date of birth** (medium, 80% confidence) — natural language date patterns.
- **IP address** (medium, 88% confidence) — full octet validation, excludes broadcast/zero.
- **Emotional distress signal** (high, 70% confidence) — hopelessness, self-worth, giving-up phrases.
- **Coercion or pressure signal** (high, 65% confidence) — language suggesting the user is being forced.

### New Python API

- `analyze_conversation(utterances: list[str]) -> ConversationResult` — multi-turn analysis.
- `ConversationTurn`, `ConversationResult` models for structured conversation output.
- `Finding.confidence: float` — detection confidence on every finding (0.0–1.0).
- `AnalysisResult.redaction_map` — ordered map of what was found and what replaced it.
- `voicesafekit conversation` CLI command — analyze multiple transcript files as one conversation.
- Updated `voicesafekit check --pretty` output now shows confidence percentage per finding.
- Updated OpenVoiceOS adapter to expose `finding_details` with confidence values.

### Scoring

- Risk score is now confidence-weighted: `score += severity_points × confidence`.
- A 70%-confidence high finding scores 25 points instead of 36, reducing false-alarm noise.

### Web app

- **Conversation mode** — toggle between Single and Conversation. Chain turns, see cumulative risk, peak decision, and all entity kinds detected across the session.
- **Inspect tab** — inline transcript highlight view. The original text stays intact; each flagged span is colored (amber = medium, red = high/critical) and hoverable for details.
- **Confidence bars** — every finding card shows a CSS bar and percentage label.
- **Copy safe transcript** — one-click clipboard copy. Keyboard shortcut: Cmd/Ctrl+Enter in single mode.
- **Export JSON** — downloads the full analysis result as a structured JSON file.
- **Five sample transcripts** — added "Identity theft" (SSN + IBAN + CVV) and "Coercion" samples alongside the existing three.
- Decision values are now color-coded: green (SAFE), green-dim (REDACT), amber (REVIEW), red (BLOCK).

### Docs

- Progress page updated with Phase 0.3 entries.
- Paper updated with new sections on confidence scoring and multi-turn analysis.
- README updated for v0.2.0 with complete API reference.

## Phase 0.2 - Integration Examples

- Added an OpenVoiceOS-style adapter helper.
- Added a runnable OpenVoiceOS pipeline example.
- Added tests for safe transcript output and emergency blocking.
- Grouped repeated finding types in summaries and the live demo.
- Improved credential detection for natural speech such as partial password phrases.
- Added a public Progress page that documents what went wrong and what was fixed.
- Added partial card reference detection for phrases such as "card ends in 4821".
- Added compact finding totals and a scrollable warning list in the Check panel.

## Phase 0.1.2 - Browser Transcription And Detector Fixes

- Added browser-based Whisper transcription for recorded audio.
- Improved payment-card detection so card numbers are not reported as phone numbers.
- Kept the live demo running from GitHub Pages.

## Phase 0.1.1 - Interface Polish

- Reworked the GitHub Pages demo with a sharper neon green and black interface.
- Added clearer Capture, Check, and Protect sections.
- Added updated screenshots and a project explanation page.

## Phase 0.1 - MVP

- Added the Python transcript checker.
- Added the command-line interface.
- Added the first privacy and safety detectors.
- Added tests, example transcripts, README, and GitHub Pages demo.
