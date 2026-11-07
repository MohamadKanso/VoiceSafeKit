SpokenPII-ASR: 108 PII utterances + 40 no-PII utterances, voice `Samantha` (macOS say), transcribed by faster-whisper `base.en`. Whisper wrote 92/108 PII utterances fully in digits/symbols.

| Detector | PII protected (not leaked) | False alarms on no-PII |
|---|---:|---:|
| VoiceSafeKit 0.6.0 | 100% (108/108) | 0% (0/40) |
| VoiceSafeKit 0.6.0 (spoken mode off) | 90% (97/108) | 0% (0/40) |
| Microsoft Presidio | 73% (79/108) | 42% (17/40) |

Note: the 0.6 fixes for issue #6 were written against the 7 misses in this set, so it is no longer held out. See RESULTS-asr-heldout.md for the unseen set.
