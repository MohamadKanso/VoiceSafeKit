# Roadmap

## Shipped

- 0.1 Browser demo, Python checker, CLI, tests
- 0.2 OpenVoiceOS adapter, grouped findings
- 0.3 Confidence scoring, SSN/IBAN/CVV/DOB/IP, distress and coercion signals, conversations
- 0.4 Encrypted exports
- 0.5 Spoken-form detection, reversible placeholders, Pipecat and LiveKit drop-ins,
  SpokenPII benchmark, zero-dependency core

## Next

- **Whisper punctuation in numbers** (found by SpokenPII-ASR): join comma-separated digit
  groups after a sensitive keyword, keywords glued to digits (`SSN609507896`), digits that
  Whisper writes as decimals, and common mishearings ("fin" for PIN).

- **Audio redaction:** map findings to STT word timestamps and bleep or mute those spans
  in recordings (`bleep_spans()`), plus a PCI "pause recording" signal.
- **Streaming input guard:** hold back interim transcripts that end in an unfinished number
  so a card split across STT chunks is still caught.
- **Home Assistant:** a redacting conversation agent (HACS) that wraps any cloud LLM agent,
  and a Wyoming proxy for `Transcript` events.
- **Gateways:** a LiteLLM custom guardrail and an Open WebUI filter function.
- **LiveKit `Redactor` backend** once livekit/agents#6342 lands.
- **Spelled-out letters and NATO alphabet** ("a for alpha"), and spoken postcodes.
- **Multilingual spoken numbers:** French, German, Spanish, Arabic.
- **MCP server** so desktop assistants can redact before sending.
