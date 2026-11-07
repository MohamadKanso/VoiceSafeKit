<p align="center">
  <img src="docs/assets/voicesafekit-cover.svg" alt="VoiceSafeKit" width="760">
</p>

<p align="center">
  <a href="https://github.com/MohamadKanso/VoiceSafeKit/actions/workflows/ci.yml"><img src="https://github.com/MohamadKanso/VoiceSafeKit/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/dependencies-0-00ff84" alt="Zero dependencies">
  <img src="https://img.shields.io/badge/python-3.10%E2%80%933.13-00ff84" alt="Python 3.10-3.13">
  <img src="https://img.shields.io/badge/license-MIT-00ff84" alt="MIT">
</p>

<p align="center">
  <a href="https://mohamadkanso.github.io/VoiceSafeKit/"><strong>Try it in your browser</strong></a>
  ·
  <a href="#spokenpii-benchmark"><strong>Benchmark</strong></a>
  ·
  <a href="#pipecat">Pipecat</a>
  ·
  <a href="#livekit-agents">LiveKit</a>
  ·
  <a href="CHANGELOG.md">Changelog</a>
</p>

# VoiceSafeKit

**Your voice agent is sending card numbers to the LLM, and your PII filter can't see them.**

Speech-to-text writes what people *say*, not what they *mean*:

```text
my card is four two four two four two four two four two four two four two four two
email me at alex dot rivera at gmail dot com
call me on oh seven seven double oh nine double oh one two three
```

Regex filters and NER models (Presidio, most guardrail libraries) are built for written
text, so they pass all three straight through. VoiceSafeKit reads speech the way STT
writes it, redacts the sensitive parts, and gives the values back when the agent needs
to say them. Zero dependencies, about 0.06 ms per utterance, and drop-in processors for
**Pipecat** and **LiveKit Agents**.

```text
User says    : Hi, my name is Alex Rivera. My card number is four two four two four two four two
               four two four two four two four two and my email is alex dot rivera at gmail dot com.
LLM receives : Hi, my name is [NAME_1]. My card number is [CARD_1] and my email is [EMAIL_1].
TTS says     : Thanks Alex Rivera. I'll send the receipt to alex dot rivera at gmail dot com.
```

<sub>Output of `examples/pipecat/offline_demo.py`, which runs without API keys.</sub>

## Install

```bash
pip install git+https://github.com/MohamadKanso/VoiceSafeKit
# extras: [pipecat]  [livekit]  [crypto] (encrypted exports)
```

```bash
echo "my pin is four eight two one" | voicesafekit redact
# my pin is [PIN removed]
```

## SpokenPII benchmark

No public benchmark measures PII *as speech-to-text writes it*, so this repo ships one.

**SpokenPII-ASR (real speech-to-text).** Spoken scripts are read aloud by a TTS voice,
digit by digit the way people say them, and transcribed by Whisper. A sample counts as
protected only if the value can't be recovered from the redacted transcript.

108 PII utterances + 40 no-PII utterances, macOS voice `Samantha`, transcribed by
faster-whisper `base.en` on CPU.

| Detector | PII protected (not leaked) | False alarms on no-PII |
|---|---:|---:|
| **VoiceSafeKit 0.5** | **94%** (101/108) | **0%** (0/40) |
| VoiceSafeKit 0.5, spoken mode off | 88% (95/108) | 0% (0/40) |
| Microsoft Presidio 2.2 | 73% (79/108) | 42% (17/40) |

Whisper `base.en` wrote 92 of the 108 utterances fully in digits, so on this engine the
gap comes as much from false alarms and voice-specific rules (PINs, one-time codes,
spoken emails) as from spoken numbers. The 7 misses show how real STT breaks PII,
and they are the next things to fix:
digit groups split by commas (`3790, 4339, 7110, 7181`), a keyword glued to the number
(`SSN609507896`), digits turned into decimals (`073, 49.95, 3022`) and a misheard keyword
(`my fin is 96-28`). These numbers come from the first run; nothing was tuned on this set.

**SpokenPII (synthetic).** 540 labelled sentences, the same values written two ways, plus
40 tricky no-PII requests ("emergency fund", "call Sue", "twenty five minutes"). A span
counts as protected only if at least 90% of it is masked.

| Detector | Written PII protected | Spoken PII protected | False alarms on no-PII | Median latency |
|---|---:|---:|---:|---:|
| **VoiceSafeKit 0.5** | **100%** | **100%** | **0%** | **0.06 ms** |
| VoiceSafeKit 0.5, spoken mode off | 100% | 11% | 0% | 0.04 ms |
| Microsoft Presidio 2.2 (spaCy `en_core_web_lg`) | 86% | 21% | 45% | 3.06 ms |

Spoken PII protected, by type:

| Type | VoiceSafeKit | Presidio |
|---|---:|---:|
| Card number | 100% | 0% |
| SSN | 100% | 3% |
| Phone | 100% | 0% |
| Email | 100% | 0% |
| PIN | 100% | 13% |
| One-time code | 100% | 3% |
| Passport | 100% | 0% |
| Date of birth | 100% | 77% |
| Name | 100% | 97% |

**Read these numbers honestly.** I wrote the synthetic set and the detector, so 100% there
mostly shows the templates are covered; the ASR set is the fairer test. Presidio is a
general-purpose tool configured with its defaults, not tuned for speech. Its false alarms
are mostly `DATE_TIME` and `PERSON` hits on ordinary requests. Reproduce everything with
`python benchmarks/run.py --presidio` and `python benchmarks/asr.py score --presidio`.
Better still, add transcripts from your own STT engine.

## What it catches

| Category | Detectors |
|---|---|
| Spoken forms | digits as words, "oh" / "double" / "triple", "plus four four", tens and hundreds, spoken emails, spoken dates |
| Payment | card number (Luhn + context), partial card ("ends in 4821"), CVV, PIN, IBAN (mod-97) |
| Identity | SSN (with or without dashes), passport, UK National Insurance, date of birth, self-introduced name |
| Contact | email, phone, street address, UK postcode, IP address |
| Credentials | passwords and secrets in speech, one-time / verification codes, API keys (OpenAI, AWS, GitHub, Slack, Google) |
| Safety signals | emergency, emotional distress, coercion, medical / legal / financial advice requests |

Every result has a `decision` (`SAFE`, `REDACT`, `REVIEW`, `BLOCK`), a 0-100 `score`,
per-finding `confidence` and `spoken` flags, a `safe_transcript`, a `redaction_map` and
plain-English `assistant_guidance`.

## Python API

```python
from voicesafekit import analyze_transcript

result = analyze_transcript("my social is four seven one, five five, eight eight four three")
result.decision            # "BLOCK"
result.safe_transcript     # "my social is [SSN removed]"
result.findings[0].spoken  # True
```

### Reversible placeholders

Plain redaction breaks agents that need to say "I've sent it to your email". A
`PrivacySession` swaps values for placeholders, keeps the map in memory, and restores
them in the reply, including streamed tokens:

```python
from voicesafekit import PrivacySession

session = PrivacySession()
safe = session.protect("email me at alex dot rivera at gmail dot com")
safe.text                       # "email me at [EMAIL_1]"
reply = llm(safe.text)          # "Done, I've emailed [EMAIL_1]."
session.restore(reply)          # "Done, I've emailed alex dot rivera at gmail dot com."

stream = session.stream()       # for token streams: "[EMA" + "IL_1]" restores correctly
```

The same value gets the same placeholder for the whole conversation, whether it was
spoken or written. **Passwords, PINs, CVVs, one-time codes and API keys are never stored,**
so the model can't make the voice read them back.

## Pipecat

```python
from voicesafekit.integrations.pipecat import voicesafe_processors

guard_in, restore_out, guard_context = voicesafe_processors()

pipeline = Pipeline([
    transport.input(), stt,
    guard_in,             # spoken PII -> [CARD_1], [EMAIL_1] before the LLM
    user_aggregator, llm,
    restore_out,          # real values back for the voice only
    tts, transport.output(),
    guard_context,        # stored assistant replies keep the placeholders
    assistant_aggregator,
])

@guard_in.event_handler("on_block")
async def on_block(processor, protected):
    ...  # emergencies, government IDs, CVVs: never forwarded, refusal is spoken
```

## LiveKit Agents

```python
from voicesafekit.integrations.livekit import VoiceSafeAgent

class Assistant(VoiceSafeAgent):          # instead of Agent
    def __init__(self):
        super().__init__(instructions="You are a helpful voice assistant.")
```

`VoiceSafeAgent` protects each user turn in `on_user_turn_completed`, restores values in
`tts_node`, and stops blocked turns. `VoiceSafeRedactor().redact(text)` is a stateless,
idempotent redactor for transcript and log hooks. Full example: `examples/livekit/agent.py`.

## OpenVoiceOS

```python
from voicesafekit.integrations.openvoiceos import protect_utterance

result = protect_utterance(utterance)
if result.should_continue:
    send_to_llm(result.safe_transcript)
```

## CLI

```bash
voicesafekit check examples/transcripts/identity_theft.txt --pretty
voicesafekit redact --placeholders < transcript.txt
voicesafekit conversation turn1.txt turn2.txt --pretty
voicesafekit check transcript.txt --out result.enc.json   # AES-256-GCM, needs [crypto]
```

## Browser app

The [live app](https://mohamadkanso.github.io/VoiceSafeKit/) records your voice,
transcribes it with Whisper on your device and runs the same rules in the browser. No
server and no API key, and nothing leaves the page. Say a card number out loud and watch
it disappear.

```bash
python3 -m http.server 8124 --directory docs   # run it locally
```

## Design principles

- **Speech first.** Rules run on what STT actually produces, not on tidy written text.
- **Local and tiny.** Pure Python, no dependencies, no network, no model download.
- **Auditable.** Every finding has a confidence score and maps to exact spans.
- **Fail toward privacy.** Credentials are never stored, blocked turns never reach the model.
- **Honest scope.** It is a fast first layer, not a full privacy programme or a
  compliance certification. Pair it with your own review for PCI DSS, HIPAA or GDPR work.

## Contributing

The most valuable contribution is a transcript your STT engine produced that VoiceSafeKit
missed (fake data only). Use the
[Missed spoken PII](https://github.com/MohamadKanso/VoiceSafeKit/issues/new?template=missed_spoken_pii.yml)
template. See [CONTRIBUTING.md](CONTRIBUTING.md) and the [roadmap](ROADMAP.md).

```bash
pip install -e ".[dev]" && pytest && python benchmarks/run.py
```

## License

MIT. See [LICENSE](LICENSE). Not legal, medical or security advice.
