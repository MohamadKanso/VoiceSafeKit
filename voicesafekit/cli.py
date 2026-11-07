from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from voicesafekit import __version__
from voicesafekit.engine import analyze_conversation, analyze_transcript
from voicesafekit.session import PrivacySession

MIN_PASSPHRASE_LENGTH = 12


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    try:
        return int(args.func(args))
    except FileNotFoundError as exc:
        print(f"voicesafekit: file not found: {exc.filename}", file=sys.stderr)
        return 2
    except IsADirectoryError as exc:
        print(f"voicesafekit: expected a file, got a folder: {exc.filename}", file=sys.stderr)
        return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voicesafekit",
        description="Check voice assistant transcripts for privacy and safety risks.",
    )
    parser.add_argument("--version", action="version", version=f"voicesafekit {__version__}")
    sub = parser.add_subparsers(dest="command")

    check = sub.add_parser("check", help="Analyze a single transcript file.")
    check.add_argument("transcript", help="Transcript file, or - to read stdin.")
    check.add_argument(
        "--no-spoken",
        action="store_true",
        help="Skip spoken-form normalisation (four two four two -> 4242).",
    )
    check.add_argument("--out", help="Optional JSON output path.")
    check.add_argument(
        "--plain-out",
        action="store_true",
        help="Write --out as plaintext JSON instead of an encrypted at-rest export.",
    )
    check.add_argument(
        "--passphrase-env",
        default="VOICESAFEKIT_EXPORT_KEY",
        help="Environment variable containing the export encryption passphrase.",
    )
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
    conversation.add_argument(
        "--plain-out",
        action="store_true",
        help="Write --out as plaintext JSON instead of an encrypted at-rest export.",
    )
    conversation.add_argument(
        "--passphrase-env",
        default="VOICESAFEKIT_EXPORT_KEY",
        help="Environment variable containing the export encryption passphrase.",
    )
    conversation.add_argument(
        "--pretty",
        action="store_true",
        help="Print a human-readable result.",
    )
    conversation.set_defaults(func=_cmd_conversation)

    redact = sub.add_parser(
        "redact",
        help="Print a redacted transcript. Reads a file or stdin; pipe-friendly.",
    )
    redact.add_argument("transcript", nargs="?", default="-", help="File, or - for stdin.")
    redact.add_argument(
        "--placeholders",
        action="store_true",
        help="Use numbered placeholders ([EMAIL_1]) instead of [email removed].",
    )
    redact.add_argument("--no-spoken", action="store_true", help="Skip spoken-form normalisation.")
    redact.set_defaults(func=_cmd_redact)

    bleep = sub.add_parser(
        "bleep",
        help="Bleep spoken PII out of a WAV recording (writes a new WAV).",
    )
    bleep.add_argument("audio", help="Input PCM WAV file.")
    bleep.add_argument("-o", "--out", required=True, help="Output WAV path.")
    bleep.add_argument(
        "--words",
        help="Word timings JSON (faster-whisper/whisper segments, Deepgram response, or a "
        "list of {word,start,end}). Without it the audio is transcribed with faster-whisper.",
    )
    bleep.add_argument("--silence", action="store_true", help="Write silence instead of a beep.")
    bleep.add_argument(
        "--padding",
        type=float,
        default=0.15,
        help="Seconds added before and after each span (default 0.15).",
    )
    bleep.add_argument("--model", default="base.en", help="faster-whisper model (default base.en).")
    bleep.add_argument("--no-spoken", action="store_true", help="Skip spoken-form normalisation.")
    bleep.add_argument(
        "--report",
        action="store_true",
        help="Print a JSON report (decision, safe transcript, spans) instead of text.",
    )
    bleep.set_defaults(func=_cmd_bleep)

    decrypt = sub.add_parser("decrypt", help="Decrypt an encrypted VoiceSafeKit JSON export.")
    decrypt.add_argument("encrypted_export", help="Encrypted VoiceSafeKit export file.")
    decrypt.add_argument("--out", help="Optional plaintext JSON output path.")
    decrypt.add_argument(
        "--passphrase-env",
        default="VOICESAFEKIT_EXPORT_KEY",
        help="Environment variable containing the export encryption passphrase.",
    )
    decrypt.set_defaults(func=_cmd_decrypt)

    return parser


def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def _cmd_check(args: argparse.Namespace) -> int:
    transcript = _read(args.transcript)
    result = analyze_transcript(transcript, spoken=not args.no_spoken)
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


def _cmd_redact(args: argparse.Namespace) -> int:
    transcript = _read(args.transcript)
    if args.placeholders:
        protected = PrivacySession(spoken=not args.no_spoken).protect(transcript)
        print(protected.text.strip())
        return 1 if protected.blocked else 0
    result = analyze_transcript(transcript, spoken=not args.no_spoken)
    print(result.safe_transcript)
    return 1 if result.decision == "BLOCK" else 0


def _cmd_bleep(args: argparse.Namespace) -> int:
    from voicesafekit.audio import bleep_file, load_words

    words = None
    if args.words:
        words = load_words(json.loads(Path(args.words).read_text(encoding="utf-8")))
    try:
        redaction = bleep_file(
            args.audio,
            args.out,
            words=words,
            model=args.model,
            spoken=not args.no_spoken,
            padding=args.padding,
            mode="silence" if args.silence else "beep",
        )
    except (ImportError, ValueError) as exc:
        raise SystemExit(f"voicesafekit bleep: {exc}") from exc
    if args.report:
        print(json.dumps({"out": args.out, **redaction.to_dict()}, indent=2))
        return 0
    print(redaction.safe_transcript)
    print()
    if not redaction.spans:
        print(f"No PII found; {args.out} is an unchanged copy.")
        return 0
    what = "Silenced" if args.silence else "Bleeped"
    print(f"{what} {len(redaction.spans)} span(s) -> {args.out}")
    for span in redaction.spans:
        print(f"  {_clock(span.start)} - {_clock(span.end)}  {span.label}")
    return 0


def _clock(seconds: float) -> str:
    minutes, secs = divmod(seconds, 60)
    return f"{int(minutes):02d}:{secs:06.3f}"


def _cmd_decrypt(args: argparse.Namespace) -> int:
    from voicesafekit.encryption import decrypt_json_payload

    encrypted = json.loads(Path(args.encrypted_export).read_text(encoding="utf-8"))
    passphrase = os.environ.get(args.passphrase_env, "")
    if not passphrase:
        raise SystemExit(f"Set {args.passphrase_env} to decrypt this VoiceSafeKit export.")
    payload = decrypt_json_payload(encrypted, passphrase)
    if args.out:
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    else:
        print(json.dumps(payload, indent=2))
    return 0


def _write_or_print(payload: dict, args: argparse.Namespace) -> None:
    if getattr(args, "out", None):
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        stored_payload = payload if args.plain_out else _encrypted_output_payload(payload, args)
        output.write_text(json.dumps(stored_payload, indent=2) + "\n", encoding="utf-8")
    elif not getattr(args, "pretty", False):
        print(json.dumps(payload, indent=2))


def _encrypted_output_payload(payload: dict, args: argparse.Namespace) -> dict[str, object]:
    try:
        from voicesafekit.encryption import encrypt_json_payload
    except ImportError as exc:
        raise SystemExit(f"{exc} Or pass --plain-out for a plaintext debug export.") from exc
    passphrase_env = args.passphrase_env
    passphrase = os.environ.get(passphrase_env, "")
    if not passphrase:
        raise SystemExit(
            f"--out writes encrypted files by default. Set {passphrase_env} "
            "or pass --plain-out for a plaintext debug export."
        )
    if len(passphrase) < MIN_PASSPHRASE_LENGTH:
        raise SystemExit(
            f"{passphrase_env} must be at least {MIN_PASSPHRASE_LENGTH} characters."
        )
    return encrypt_json_payload(payload, passphrase)


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
        spoken = " [spoken]" if finding.get("spoken") else ""
        print(
            f"  - {finding['label']} ({finding['severity']}, "
            f"{conf}% confidence){spoken}: {finding['explanation']}"
        )


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
