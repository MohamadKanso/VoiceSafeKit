"""Bleep spoken PII out of a call recording, locally.

    python examples/audio/bleep_recording.py                   # self-contained demo
    python examples/audio/bleep_recording.py call.wav -o out.wav   # needs voicesafekit[audio]

With no arguments it writes a synthetic 16 kHz "recording" plus hand-made word
timings (what an STT engine with word timestamps returns) and bleeps it: no extras,
no network. With a WAV path it transcribes with faster-whisper first.
"""

from __future__ import annotations

import argparse
import math
import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from voicesafekit.audio import Word, bleep_file, bleep_wav, redact_audio_spans  # noqa: E402

SCRIPT = (
    "hi my name is Alex Rivera my card number is four two four two four two four two "
    "four two four two four two four two and my pin is four eight two one thanks"
)
RATE = 16000


def demo_recording(path: Path) -> list[Word]:
    """A 'voice-like' warble per word and the matching word timings."""
    words, frames, t = [], bytearray(), 0.3
    for text in SCRIPT.split():
        length = 0.18 + 0.03 * len(text)
        words.append(Word(text, round(t, 3), round(t + length, 3)))
        t += length + 0.08
    total = int((t + 0.3) * RATE)
    for n in range(total):
        sec = n / RATE
        voiced = any(w.start <= sec < w.end for w in words)
        value = 0.3 * math.sin(2 * math.pi * 180 * sec) * math.sin(2 * math.pi * 4 * sec)
        frames += int(32767 * value * voiced).to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(bytes(frames))
    return words


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("audio", nargs="?", help="PCM WAV to bleep (transcribed with Whisper).")
    parser.add_argument("-o", "--out", help="Output WAV (default: next to the input / temp dir).")
    parser.add_argument("--silence", action="store_true", help="Silence instead of a beep.")
    args = parser.parse_args()
    mode = "silence" if args.silence else "beep"

    if args.audio:
        src = Path(args.audio)
        out = Path(args.out) if args.out else src.with_name(src.stem + ".bleeped.wav")
        redaction = bleep_file(src, out, mode=mode)
    else:
        folder = Path(args.out).parent if args.out else Path(tempfile.mkdtemp(prefix="vsk-"))
        src = folder / "demo-call.wav"
        out = Path(args.out) if args.out else folder / "demo-call.bleeped.wav"
        words = demo_recording(src)
        redaction = redact_audio_spans(words)
        bleep_wav(src, out, redaction, mode=mode)

    print("Safe transcript:", redaction.safe_transcript)
    for span in redaction.spans:
        print(f"  {span.start:6.2f}s - {span.end:6.2f}s  {span.label}")
    print(f"Wrote {out}  (original: {src})")


if __name__ == "__main__":
    main()
