SpokenPII-ASR: 108 PII utterances + 40 no-PII utterances, voice `Daniel` (macOS say), transcribed by faster-whisper `small.en`. Whisper wrote 89/108 PII utterances fully in digits/symbols.

| Detector | PII protected (not leaked) | False alarms on no-PII |
|---|---:|---:|
| VoiceSafeKit 0.6.0 | 98% (106/108) | 2% (1/40) |
| VoiceSafeKit 0.6.0 (spoken mode off) | 87% (94/108) | 2% (1/40) |
| Microsoft Presidio | 65% (70/108) | 42% (17/40) |

VoiceSafeKit 0.5 (before the 0.6 fixes) on the same held-out set: 94% (102/108), 1/40 false alarms.
This set was transcribed before any 0.6 change and was not used for tuning.
