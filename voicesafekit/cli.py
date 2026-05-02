from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from voicesafekit import __version__
from voicesafekit.engine import analyze_transcript


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

    check = sub.add_parser("check", help="Analyze a transcript file.")
    check.add_argument("transcript", help="Text file containing the voice transcript.")
    check.add_argument("--out", help="Optional JSON output path.")
    check.add_argument("--pretty", action="store_true", help="Print a human-readable result.")
    check.set_defaults(func=_cmd_check)
    return parser


def _cmd_check(args: argparse.Namespace) -> int:
    transcript = Path(args.transcript).read_text(encoding="utf-8")
    result = analyze_transcript(transcript)
    if args.out:
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
    if args.pretty:
        _print_pretty(result.to_dict())
    else:
        print(json.dumps(result.to_dict(), indent=2))
    return 1 if result.decision == "BLOCK" else 0


def _print_pretty(payload: dict[str, object]) -> None:
    print(f"Decision: {payload['decision']}")
    print(f"Risk score: {payload['score']}/100")
    print(f"Summary: {payload['summary']}")
    print("\nSafe transcript:")
    print(payload["safe_transcript"])
    print("\nAssistant guidance:")
    for item in payload["assistant_guidance"]:
        print(f"- {item}")
    print("\nFindings:")
    for finding in payload["findings"]:
        print(f"- {finding['label']} ({finding['severity']}): {finding['explanation']}")


if __name__ == "__main__":
    sys.exit(main())

