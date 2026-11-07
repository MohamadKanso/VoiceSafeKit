SpokenPII-ASR: 108 PII utterances + 40 no-PII utterances, voice `Samantha` (macOS say), transcribed by faster-whisper `base.en`. Whisper wrote 92/108 PII utterances fully in digits/symbols.

| Detector | PII protected (not leaked) | False alarms on no-PII |
|---|---:|---:|
| VoiceSafeKit 0.5 | 94% (101/108) | 0% (0/40) |
| VoiceSafeKit 0.5 (spoken mode off) | 88% (95/108) | 0% (0/40) |
| Microsoft Presidio | 73% (79/108) | 42% (17/40) |
