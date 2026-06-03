from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from voicesafekit import __version__
from voicesafekit.engine import analyze_conversation, analyze_transcript


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return int(args.func(args))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voicesafekit",
        description="Check voice assistant transcripts for privacy and safety risks.",
    )
    parser.add_argument("--version", action="version", version=f"voicesafekit {__version__}")
    sub = parser.add_subparsers(dest="command")

    check = sub.add_parser("check", help="Analyze a single transcript file.")
    check.add_argument("transcript", help="Text file containing the voice transcript.")
    check.add_argument("--out", help="Optional JSON output path.")
    check.add_argument("--pretty", action="store_true", help="Print a human-readable result.")
    check.set_defaults(func=_cmd_check)

    conversation = sub.add_parser(
        "conversation",
        help="Analyze multiple transcript files as a conversation.",
    )
    conversation.add_argument(
        "transcripts",
        nargs="+",
        help="Text files, one per conversation turn (in order).",
    )
    conversation.add_argument("--out", help="Optional JSON output path.")
    conversation.add_argument("--pretty", action="store_true", help="Print a human-readable result.")
    conversation.set_defaults(func=_cmd_conversation)

    return parser


def _cmd_check(args: argparse.Namespace) -> int:
    transcript = Path(args.transcript).read_text(encoding="utf-8")
    result = analyze_transcript(transcript)
    payload = result.to_dict()
    _write_or_print(payload, args)
    if args.pretty:
        _print_pretty_single(payload)
    return 1 if result.decision == "BLOCK" else 0


def _cmd_conversation(args: argparse.Namespace) -> int:
    utterances = [Path(p).read_text(encoding="utf-8") for p in args.transcripts]
    result = analyze_conversation(utterances)
    payload = result.to_dict()
    _write_or_print(payload, args)
    if args.pretty:
        _print_pretty_conversation(payload)
    return 1 if result.peak_decision == "BLOCK" else 0


def _write_or_print(payload: dict, args: argparse.Namespace) -> None:
    if getattr(args, "out", None):
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    elif not getattr(args, "pretty", False):
        print(json.dumps(payload, indent=2))


def _print_pretty_single(payload: dict) -> None:
    print(f"Decision:    {payload['decision']}")
    print(f"Risk score:  {payload['score']}/100")
    print(f"Summary:     {payload['summary']}")
    print("\nSafe transcript:")
    print(payload["safe_transcript"])
    print("\nAssistant guidance:")
    for item in payload["assistant_guidance"]:
        print(f"  - {item}")
    print("\nFindings:")
    for finding in payload["findings"]:
        conf = round(finding["confidence"] * 100)
        print(f"  - {finding['label']} ({finding['severity']}, {conf}% confidence): {finding['explanation']}")


def _print_pretty_conversation(payload: dict) -> None:
    print(f"Conversation: {len(payload['turns'])} turns")
    print(f"Peak decision: {payload['peak_decision']}")
    print(f"Cumulative score: {payload['cumulative_score']}/100")
    if payload["seen_kinds"]:
        print(f"Entity kinds seen: {', '.join(payload['seen_kinds'])}")
    for i, turn in enumerate(payload["turns"], 1):
        r = turn["result"]
        print(f"\n--- Turn {i} ({r['decision']}, score {r['score']}) ---")
        print(f"  {turn['transcript'][:120]}{'...' if len(turn['transcript']) > 120 else ''}")
        for finding in r["findings"]:
            conf = round(finding["confidence"] * 100)
            print(f"  [{finding['severity'].upper()}] {finding['label']} ({conf}% conf)")


if __name__ == "__main__":
    sys.exit(main())
