# Changelog

This file records the visible phases of VoiceSafeKit so the project history is
easy to follow.

## Phase 0.6 - Reach and Real Speech (7 November 2026)

VoiceSafeKit now plugs into the two biggest self-hosted LLM gateways, redacts call
recordings as well as transcripts, and is measured on a held-out real-speech set.

### Real speech

- Whisper often punctuates one spoken number like a list (`my visa, 3790, 4339, 7110, 7181`),
  glues keywords to digits (`SSN609507896`) or writes digits as decimals. Digit groups right
  after a sensitive word are now joined before detection; years, prices, room numbers and
  scores stay untouched (#6).
- Emails where speech-to-text dropped the "at" (`alex.rivera.gmail.com`) are caught for
  well-known providers. "log in at mail.yahoo.com" no longer reads as a spoken email.
- "fin" (a common Whisper mishearing of "PIN") is treated as PIN when digits follow.
- A card number where STT repeated a group (`4242-4242-4242-4242-4242`, 20 digits) is still
  caught when card words are nearby. Found by driving the live demo with a TTS voice as the
  microphone: in-browser Whisper heard one group twice and the number went through.
- **Held-out benchmark:** new scripts, a British TTS voice and Whisper `small.en`, frozen
  before any change: 0.6 protects 106/108 (0.5: 102/108, Presidio: 70/108) with 1/40 false
  alarms. The three failures are public in #9.

### Integrations

- **Pipecat:** a number split across two final transcription frames no longer leaks. The
  input processor holds a fragment that ends mid-number near a sensitive word for up to
  0.8 s and merges it with the next frame (#7).
- **Open WebUI** Filter Function (paste-in file), with per-chat placeholders, streamed
  restore, history handling and blocking of critical new messages.
- **LiteLLM** custom guardrail: redact before the model, restore after (streaming too),
  HTTP 400 for critical data. Tested on a running LiteLLM 1.108 proxy.

### Audio

- `voicesafekit bleep` and `voicesafekit.audio`: map findings to word timestamps (faster-
  whisper, Deepgram, WhisperX or plain dicts) and beep or silence those spans in PCM WAV
  files. Standard library only; faster-whisper is optional (`[audio]`).

### Packaging

- Version 0.6.0. Release workflow publishes to PyPI with trusted publishing (no tokens),
  checks the tag matches the version, and runs as a dry run when started by hand.
- CLI: a missing file prints a one-line error instead of a traceback.
- New extras: `audio`, `openwebui`, `litellm`. CI gains a gateways job.

## Phase 0.5 - Voice-Native Detection (7 November 2026)

Speech-to-text engines often write what people say, not what they mean:
"four two four two ...", "alex dot rivera at gmail dot com", "oh seven seven double oh".
Before this release VoiceSafeKit, like every regex or NER PII tool, returned SAFE for all of
them. This release makes spoken-form PII the core of the project.

### Detection

- **Spoken-form normaliser** (`voicesafekit/spoken.py`): spoken digits, "oh/zero/nought",
  "double/triple", "plus four four", "nine hundred", tens ("forty two"), spoken emails
  ("dot", "at", "underscore"), and spoken dates ("march fourth", "the twenty first of may").
  Detection runs on the written form; redaction maps back to the original words.
- `Finding.spoken` marks findings that were only caught in spoken form.
- New detectors: PIN, one-time/verification code, passport number, UK National Insurance
  number, SSN without dashes after "social"/"SSN", API key formats (OpenAI, AWS, GitHub,
  Slack, Google), self-introduced names, UK postcodes.
- Value-only redaction for the new detectors: "my pin is [PIN removed]" keeps the context.

### Fixes

- Payment card pattern was lazy and could stop after 13 digits, leaving the last digits of
  some card numbers unredacted. It now matches the full number.
- "my password for netflix is hunter22" was missed. It is now caught.
- False alarms removed: "emergency fund" (was BLOCK), "call Sue" (was legal), "secret
  ingredient" and "password reset" (were secrets), ISO dates and passport numbers read as
  phone numbers.

### Reversible redaction

- `PrivacySession.protect()` swaps personal data for numbered placeholders (`[EMAIL_1]`),
  consistent across turns and across spoken/written forms of the same value.
- `restore()` and `stream()` put real values back into model output, including streamed
  tokens that split a placeholder. `reprotect()` swaps them out again for stored context.
- Credentials (passwords, PINs, CVVs, one-time codes, API keys) are never stored and can
  never be restored into a reply.

### Integrations

- **Pipecat**: `VoiceSafeInputProcessor`, `VoiceSafeOutputProcessor`,
  `VoiceSafeContextGuard` and `voicesafe_processors()`, with `on_decision` / `on_block`
  events and a spoken refusal on BLOCK. Tested against Pipecat 1.15.
- **LiveKit Agents**: `VoiceSafeAgent` (protects the user turn, restores values in
  `tts_node`, stops blocked turns) and an idempotent `VoiceSafeRedactor`. Tested against
  LiveKit Agents 1.8.

### Benchmark

- **SpokenPII** (`benchmarks/`): 540 labelled PII sentences in written and spoken form plus
  40 tricky no-PII sentences, with a runner that compares against Microsoft Presidio.
- **SpokenPII-ASR**: the spoken scripts read aloud by a TTS voice and transcribed by
  Whisper, so the transcripts come from a real STT engine.

### Packaging and tooling

- Zero runtime dependencies. Encrypted exports moved to the `crypto` extra.
- New extras: `pipecat`, `livekit`.
- New CLI command: `voicesafekit redact` (stdin-friendly, `--placeholders`), `check -`
  reads stdin, `--no-spoken` turns normalisation off.
- GitHub Actions CI: Python 3.10-3.13, a zero-dependency job and an integrations job.

## Phase 0.4 - Saved Export Protection (15 June 2026)

Saved VoiceSafeKit results now have a safer default. The filter still reads the
transcript in memory because the rules need plain text. The saved JSON file is
different: it can now be encrypted so the redaction map is not left readable on
disk.

### Security

- Added AES-256-GCM encrypted export files with PBKDF2-HMAC-SHA256 key derivation.
- Browser Export now downloads encrypted JSON using the Web Crypto API and a local export key.
- CLI `--out` now writes encrypted files by default using `VOICESAFEKIT_EXPORT_KEY`.
- Added `voicesafekit decrypt` for opening an encrypted export again.
- Added `--plain-out` as an explicit local debugging escape hatch.
- Documented that TLS/HTTPS protects data in transit. AES-GCM protects saved files on disk.

### Tests

- Added encryption round-trip coverage to verify sensitive values are hidden in stored files.
- Added CLI coverage proving default `--out` artifacts are encrypted.

## Phase 0.3 - Intelligence and Context (3 June 2026)

A larger detection upgrade, shaped by real voice AI safety patterns and the way
conversational speech can carry context.

### New detectors (Python + browser)

- **Social Security Number** (critical, 95% confidence): pattern plus invalid-range filter.
- **IBAN / Bank account** (critical, 88% confidence): pattern plus mod-97 checksum validation.
- **Card security code / CVV** (critical, 93% confidence): keyword-triggered exact match.
- **Date of birth** (medium, 80% confidence): natural language date patterns.
- **IP address** (medium, 88% confidence): full octet validation, excludes broadcast and zero.
- **Emotional distress signal** (high, 70% confidence): hopelessness, self-worth and giving-up phrases.
- **Coercion or pressure signal** (high, 65% confidence): language suggesting the user is being forced.

### New Python API

- `analyze_conversation(utterances: list[str]) -> ConversationResult`: multi-turn analysis.
- `ConversationTurn`, `ConversationResult` models for structured conversation output.
- `Finding.confidence: float`: detection confidence on every finding (0.0-1.0).
- `AnalysisResult.redaction_map`: ordered map of what was found and what replaced it.
- `voicesafekit conversation` CLI command: analyze multiple transcript files as one conversation.
- Updated `voicesafekit check --pretty` output now shows confidence percentage per finding.
- Updated OpenVoiceOS adapter to expose `finding_details` with confidence values.

### Scoring

- Risk score is now confidence-weighted: `score += severity_points × confidence`.
- A 70%-confidence high finding scores 25 points instead of 36, reducing false-alarm noise.

### Web app

- **Conversation mode**: toggle between Single and Conversation. Chain turns, see cumulative risk, peak decision and all entity kinds detected across the session.
- **Inspect tab**: inline transcript highlight view. The original text stays intact. Each flagged span is colored and hoverable for details.
- **Confidence bars**: every finding card shows a CSS bar and percentage label.
- **Copy safe transcript**: one-click clipboard copy. Keyboard shortcut: Cmd/Ctrl+Enter in single mode.
- **Export JSON**: downloads the full analysis result as a structured JSON file.
- **Five sample transcripts**: added "Identity theft" (SSN + IBAN + CVV) and "Coercion" samples alongside the existing three.
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
- Added clearer Capture, Check and Protect sections.
- Added updated screenshots and a project explanation page.

## Phase 0.1 - MVP

- Added the Python transcript checker.
- Added the command-line interface.
- Added the first privacy and safety detectors.
- Added tests, example transcripts, README and GitHub Pages demo.
