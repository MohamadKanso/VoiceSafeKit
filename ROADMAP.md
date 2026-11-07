# Roadmap

## Shipped

- 0.1 Browser demo, Python checker, CLI, tests
- 0.2 OpenVoiceOS adapter, grouped findings
- 0.3 Confidence scoring, SSN/IBAN/CVV/DOB/IP, distress and coercion signals, conversations
- 0.4 Encrypted exports
- 0.5 Spoken-form detection, reversible placeholders, Pipecat and LiveKit drop-ins,
  SpokenPII benchmark, zero-dependency core
- 0.6 Whisper number formatting, Pipecat split frames, Open WebUI and LiteLLM adapters,
  audio bleeping, held-out real-speech benchmark, PyPI release workflow

## Next

- **Held-out failures** from the 0.6 benchmark: PIN written as money, comma before a
  birth year, a mangled date read as a phone. [#9](https://github.com/MohamadKanso/VoiceSafeKit/issues/9)
- **Audio in the browser demo:** play back your recording with the PII bleeped.
- **More STT engines in SpokenPII-ASR** (help wanted). [#8](https://github.com/MohamadKanso/VoiceSafeKit/issues/8)
- **Home Assistant:** a redacting conversation agent (HACS) that wraps any cloud LLM agent,
  and a Wyoming proxy for `Transcript` events ([#2](https://github.com/MohamadKanso/VoiceSafeKit/issues/2)).
- **LiveKit `Redactor` backend** once livekit/agents#6342 lands.
- **Spelled-out letters and NATO alphabet** ("a for alpha"), and spoken postcodes.
- **Multilingual spoken numbers:** French, German, Spanish, Arabic.
- **MCP server** so desktop assistants can redact before sending.
