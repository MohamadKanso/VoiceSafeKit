"""SpokenPII-ASR: real speech-to-text output, not hand-written transcripts.

1. Each spoken script from SpokenPII is read aloud by a text-to-speech voice
   (macOS ``say``), digit by digit the way a person would say it.
2. The audio is transcribed by Whisper (faster-whisper). Whisper decides whether
   to write "4242" or "four two four two"; nothing here is tuned to its output.
3. A detector "leaks" a sample if the sensitive value is still recoverable from
   the redacted transcript (checked after spoken-form normalisation, so "four
   two four two" left in the text counts as a leak).

    python benchmarks/asr.py transcribe   # needs macOS + faster-whisper (slow, cached)
    python benchmarks/asr.py score [--presidio] [--data FILE.jsonl]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from voicesafekit.spoken import normalize_spoken  # noqa: E402

DATA = ROOT / "data" / "spokenpii.jsonl"
ASR = ROOT / "data" / "spokenpii-asr.jsonl"
PER_TYPE = 12


def gold_value(row: dict) -> tuple[str, str]:
    entity = row["entities"][0]
    raw = row["text"][entity["start"] : entity["end"]]
    written = normalize_spoken(raw).text
    kind = entity["type"]
    if kind == "email":
        return kind, written.lower()
    if kind == "name":
        return kind, raw.split()[-1].lower()
    if kind == "dob":
        return kind, re.findall(r"\d{4}", written)[-1]
    return kind, re.sub(r"\D", "", written)


def leaked(kind: str, value: str, redacted: str) -> bool:
    written = normalize_spoken(redacted).text.lower()
    if kind == "email":
        local = re.split(r"[._@]", value)[0]
        return local in written and "@" in written
    if kind in ("name", "dob"):
        return value in written
    digits = re.sub(r"\D", "", written)
    # Any 4 consecutive digits of the value left in the text is a leak.
    window = min(4, len(value))
    return any(value[i : i + window] in digits for i in range(len(value) - window + 1))


def _read_wav(path: Path):
    import wave

    import numpy as np

    with wave.open(str(path)) as wav:
        frames = wav.readframes(wav.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def transcribe(model_name: str, voice: str) -> None:
    from faster_whisper import WhisperModel

    rows = [json.loads(line) for line in DATA.read_text().splitlines() if line]
    picked, counts = [], {}
    for row in rows:
        if row["form"] == "spoken":
            kind = row["entities"][0]["type"]
            if counts.get(kind, 0) < PER_TYPE:
                counts[kind] = counts.get(kind, 0) + 1
                picked.append(row)
        elif row["form"] == "negative":
            picked.append(row)

    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, row in enumerate(picked):
            wav = Path(tmp) / f"{i}.wav"
            subprocess.run(
                ["say", "-v", voice, "-o", str(wav), "--data-format=LEI16@16000", row["text"]],
                check=True,
            )
            segments, _ = model.transcribe(_read_wav(wav), language="en", beam_size=5)
            text = " ".join(s.text.strip() for s in segments).strip()
            item = {"id": row["id"], "script": row["text"], "asr": text, "form": row["form"],
                    "model": model_name, "voice": voice}
            if row["form"] == "spoken":
                item["type"], item["value"] = gold_value(row)
            out.append(item)
            print(f"[{i + 1}/{len(picked)}] {text}", file=sys.stderr)
    ASR.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out))


def score(use_presidio: bool, data: Path = ASR) -> None:
    from run import presidio_detector, vsk_detector

    rows = [json.loads(line) for line in Path(data).read_text().splitlines() if line]
    detectors = [("VoiceSafeKit 0.5", vsk_detector(True)),
                 ("VoiceSafeKit 0.5 (spoken mode off)", vsk_detector(False))]
    if use_presidio:
        detectors.append(("Microsoft Presidio", presidio_detector()))

    model = rows[0]["model"]
    voice = rows[0]["voice"]
    pii = [r for r in rows if r["form"] == "spoken"]
    neg = [r for r in rows if r["form"] == "negative"]
    written_by_whisper = sum(
        1 for r in pii if not re.search(r"\b(?:zero|oh|one|two|three|four|five|six|seven|"
                                        r"eight|nine|dot|at)\b", r["asr"].lower())
    )
    print(f"SpokenPII-ASR: {len(pii)} PII utterances + {len(neg)} no-PII utterances, "
          f"voice `{voice}` (macOS say), transcribed by faster-whisper `{model}`. "
          f"Whisper wrote {written_by_whisper}/{len(pii)} PII utterances fully in digits/symbols.")
    print()
    print("| Detector | PII protected (not leaked) | False alarms on no-PII |")
    print("|---|---:|---:|")
    for name, detect in detectors:
        safe = 0
        for r in pii:
            spans = sorted(detect(r["asr"]), reverse=True)
            text = r["asr"]
            for s, e in spans:
                text = text[:s] + "[X]" + text[e:]
            safe += not leaked(r["type"], r["value"], text)
        alarms = sum(1 for r in neg if detect(r["asr"]))
        print(f"| {name} | {safe / len(pii):.0%} ({safe}/{len(pii)}) | "
              f"{alarms / len(neg):.0%} ({alarms}/{len(neg)}) |")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("transcribe")
    t.add_argument("--model", default="base.en")
    t.add_argument("--voice", default="Samantha")
    s = sub.add_parser("score")
    s.add_argument("--presidio", action="store_true")
    s.add_argument("--data", default=str(ASR), help="ASR transcripts JSONL to score.")
    args = parser.parse_args()
    if args.cmd == "transcribe":
        transcribe(args.model, args.voice)
    else:
        score(args.presidio, Path(args.data))


if __name__ == "__main__":
    main()
