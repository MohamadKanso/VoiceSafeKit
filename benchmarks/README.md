# SpokenPII

A benchmark for PII as speech-to-text writes it.

| File | What it is |
|---|---|
| `data/spokenpii.jsonl` | 580 synthetic sentences: 270 written PII, 270 spoken PII, 40 tricky no-PII. Gold spans included. All values are fake. |
| `data/spokenpii-asr.jsonl` | 148 of those scripts read aloud by a TTS voice and transcribed by Whisper `base.en`. |
| `generate.py` | Rebuilds `spokenpii.jsonl` (seeded, deterministic). |
| `run.py` | Scores detectors on the synthetic set. `--presidio` adds Microsoft Presidio. |
| `asr.py` | `transcribe` rebuilds the ASR set (macOS + faster-whisper), `score` evaluates it. |
| `RESULTS.md`, `RESULTS-asr.md` | Latest results. |

Scoring rules:

- **Synthetic:** a gold span is protected only if 90% or more of its non-space characters are redacted.
- **ASR:** a sample leaks if the value can still be recovered from the redacted transcript
  after spoken-form normalisation (any 4 consecutive digits of a number, the email's local
  part plus `@`, the surname, or the birth year).
- **False alarms:** a no-PII sentence counts as a false alarm if anything in it was redacted.

The synthetic set was written by the same author as the detector, so treat it as a
regression suite. The ASR set is closer to real use. Transcripts from other STT engines
(Deepgram, Vosk, Parakeet, Moonshine, cloud APIs) are very welcome.
