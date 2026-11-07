"""Run the SpokenPII benchmark.

    python benchmarks/run.py                 # VoiceSafeKit only
    pip install presidio-analyzer && python -m spacy download en_core_web_lg
    python benchmarks/run.py --presidio      # adds Microsoft Presidio

Metric: a gold span counts as *protected* only if at least 90% of its
non-space characters are covered by redacted spans. Partially masking a card
number still leaks it, so partial hits do not count.
False-alarm rate: share of no-PII sentences where anything was redacted.
Latency: median wall time per sentence after warm-up, single thread.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from voicesafekit import analyze_transcript  # noqa: E402
from voicesafekit.rules import INTENT_RULES  # noqa: E402

INTENT_KINDS = {r.kind for r in INTENT_RULES}
Span = tuple[int, int]


def vsk_detector(spoken: bool):
    def detect(text: str) -> list[Span]:
        result = analyze_transcript(text, spoken=spoken)
        return [(f.start, f.end) for f in result.findings if f.kind not in INTENT_KINDS]

    return detect


def presidio_detector():
    from presidio_analyzer import AnalyzerEngine

    engine = AnalyzerEngine()
    entities = [
        "CREDIT_CARD", "US_SSN", "EMAIL_ADDRESS", "PHONE_NUMBER", "PERSON", "DATE_TIME",
        "US_PASSPORT", "US_BANK_NUMBER", "IBAN_CODE", "IP_ADDRESS", "UK_NHS",
    ]

    def detect(text: str) -> list[Span]:
        return [(r.start, r.end) for r in engine.analyze(text, language="en", entities=entities)]

    return detect


def protected(text: str, gold: dict, spans: list[Span]) -> bool:
    chars = [i for i in range(gold["start"], gold["end"]) if not text[i].isspace()]
    covered = sum(1 for i in chars if any(s <= i < e for s, e in spans))
    return bool(chars) and covered / len(chars) >= 0.9


def evaluate(name: str, detect, rows: list[dict]) -> dict:
    for row in rows[:20]:  # warm-up
        detect(row["text"])
    hits: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    false_alarms = 0
    negatives = 0
    timings = []
    for row in rows:
        start = time.perf_counter()
        spans = detect(row["text"])
        timings.append((time.perf_counter() - start) * 1000)
        if row["form"] == "negative":
            negatives += 1
            false_alarms += bool(spans)
            continue
        for gold in row["entities"]:
            key = (row["form"], gold["type"])
            hits[key][1] += 1
            hits[key][0] += protected(row["text"], gold, spans)
    by_form = defaultdict(lambda: [0, 0])
    for (form, _), (h, n) in hits.items():
        by_form[form][0] += h
        by_form[form][1] += n
    return {
        "name": name,
        "recall": {f: h / n for f, (h, n) in by_form.items()},
        "by_type": {f"{form}/{t}": h / n for (form, t), (h, n) in sorted(hits.items())},
        "false_alarm_rate": false_alarms / negatives if negatives else 0.0,
        "median_ms": statistics.median(timings),
    }


def markdown(results: list[dict], n_rows: int) -> str:
    lines = [
        f"SpokenPII v1: {n_rows} sentences "
        "(270 written PII, 270 spoken PII, 40 tricky no-PII).",
        "",
        "| Detector | Written PII protected | Spoken PII protected | False alarms on no-PII "
        "| Median latency |",
        "|---|---:|---:|---:|---:|",
    ]
    for r in results:
        lines.append(
            f"| {r['name']} | {r['recall'].get('written', 0):.0%} | "
            f"{r['recall'].get('spoken', 0):.0%} | {r['false_alarm_rate']:.0%} | "
            f"{r['median_ms']:.2f} ms |"
        )
    types = sorted({k.split("/")[1] for r in results for k in r["by_type"]})
    lines += ["", "Spoken PII protected, by type:", ""]
    lines.append("| Type | " + " | ".join(r["name"] for r in results) + " |")
    lines.append("|---|" + "---:|" * len(results))
    for t in types:
        cells = [f"{r['by_type'].get(f'spoken/{t}', 0):.0%}" for r in results]
        lines.append(f"| {t} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=str(ROOT / "data" / "spokenpii.jsonl"))
    parser.add_argument("--presidio", action="store_true")
    parser.add_argument("--json", help="Write raw results to this path.")
    args = parser.parse_args()

    rows = [json.loads(line) for line in Path(args.data).read_text().splitlines() if line]
    results = [
        evaluate("VoiceSafeKit 0.5", vsk_detector(True), rows),
        evaluate("VoiceSafeKit 0.5 (spoken mode off)", vsk_detector(False), rows),
    ]
    if args.presidio:
        results.append(evaluate("Microsoft Presidio", presidio_detector(), rows))
    print(markdown(results, len(rows)))
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
