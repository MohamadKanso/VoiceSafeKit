# Contributing

Thank you for considering a contribution to VoiceSafeKit.

The most useful contributions, in order:

1. **Report a missed spoken form.** Paste the exact transcript your speech-to-text engine
   produced (fake data only) using the "Missed spoken PII" issue template. It becomes a
   test and a benchmark row.
2. **Add SpokenPII-ASR transcripts from another STT engine** (Deepgram, Vosk, Parakeet,
   Moonshine ...). See `benchmarks/asr.py`.
3. **Add a detector or a language.** Detectors live in `voicesafekit/rules.py`; spoken
   number words live in `voicesafekit/spoken.py`.
4. **Add an integration** for a voice framework (Home Assistant, Wyoming, Vocode, TEN).

Keep the core dependency-free, readable and privacy-first. The browser demo in `docs/app.js`
mirrors the Python rules, so detector changes should land in both.

Before opening a pull request, run:

```bash
python3 -m pytest
python3 -m ruff check voicesafekit tests benchmarks
python3 benchmarks/run.py   # the SpokenPII numbers must not go down
```
