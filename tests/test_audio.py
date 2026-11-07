"""Audio redaction tests. Standard library only: no ASR, no numpy."""

from __future__ import annotations

import json
import math
import random
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from voicesafekit.audio import (
    AudioSpan,
    Word,
    bleep_file,
    bleep_wav,
    load_words,
    redact_audio_spans,
    words_from_deepgram,
    words_from_dicts,
    words_from_whisper,
)
from voicesafekit.cli import main

SENTENCE = (
    "my card number is "
    + " ".join(["four two"] * 8)
    + " and my email is alex dot rivera at gmail dot com"
)
CARD_WORDS = range(4, 20)  # the 16 spoken digits
EMAIL_WORDS = range(24, 31)  # alex dot rivera at gmail dot com
RAW_VALUES = ("four two four two", "4242", "alex dot rivera", "rivera", "gmail")
RATE = 8000


def _words(text: str = SENTENCE, step: float = 0.4, length: float = 0.3) -> list[Word]:
    return [
        Word(text=w, start=round(0.2 + i * step, 3), end=round(0.2 + i * step + length, 3))
        for i, w in enumerate(text.split())
    ]


def _write_wav(path: Path, seconds: float, *, channels: int = 1, width: int = 2) -> None:
    """Deterministic noise, never silent and never a pure tone."""
    rng = random.Random(7)
    peak = 2 ** (8 * width - 1) - 1
    frames = bytearray()
    for _ in range(int(seconds * RATE)):
        for _ in range(channels):
            value = int(rng.uniform(-0.5, 0.5) * peak) or 1
            if width == 1:
                frames.append(value + 128)
            else:
                frames += value.to_bytes(width, "little", signed=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(RATE)
        wav.writeframes(bytes(frames))


def _frames(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as wav:
        return wav.readframes(wav.getnframes()), wav.getnchannels() * wav.getsampwidth()


def _samples(raw: bytes, width: int) -> list[int]:
    if width == 1:
        return [b - 128 for b in raw]
    return [int.from_bytes(raw[i : i + width], "little", signed=True)
            for i in range(0, len(raw), width)]


def _span_frames(spans) -> list[tuple[int, int]]:
    return [(math.floor(s * RATE), math.ceil(e * RATE)) for s, e in spans]


@pytest.fixture
def words() -> list[Word]:
    return _words()


@pytest.fixture
def wav(tmp_path) -> Path:
    path = tmp_path / "in.wav"
    _write_wav(path, 14.0)
    return path


# Spans


def test_spans_cover_exactly_the_card_and_email_words(words) -> None:
    redaction = redact_audio_spans(words, padding=0.15)
    assert [s.kind for s in redaction.spans] == ["payment_card", "email"]
    card, email = redaction.spans
    assert card.start == pytest.approx(words[CARD_WORDS[0]].start - 0.15)
    assert card.end == pytest.approx(words[CARD_WORDS[-1]].end + 0.15)
    assert email.start == pytest.approx(words[EMAIL_WORDS[0]].start - 0.15)
    assert email.end == pytest.approx(words[EMAIL_WORDS[-1]].end + 0.15)
    # Words around the PII ("is", "and", "is") stay audible.
    for i in (3, 20, 23):
        assert not any(s.start < words[i].start and words[i].end < s.end for s in redaction.spans)
    assert redaction.safe_transcript == (
        "my card number is [payment number removed] and my email is [email removed]"
    )


def test_padding_clamps_at_zero() -> None:
    words = [Word("alex@example.com", 0.05, 0.9), Word("is", 0.95, 1.1), Word("my", 1.15, 1.3),
             Word("email", 1.35, 1.7)]
    redaction = redact_audio_spans(words, padding=0.3)
    assert [s.kind for s in redaction.spans] == ["email"]
    assert redaction.spans[0].start == 0.0
    assert redaction.spans[0].end == pytest.approx(1.2)


def test_merged_span_lists_every_kind() -> None:
    words = _words("my pin is four eight two one email alex@example.com", step=0.3)
    redaction = redact_audio_spans(words, padding=0.5)
    assert len(redaction.spans) == 1
    assert redaction.spans[0].kind == "pin+email"
    assert "PIN" in redaction.spans[0].label and "Email" in redaction.spans[0].label


def test_intent_findings_are_not_bleeped() -> None:
    words = _words("i have chest pain and my email is alex@example.com")
    redaction = redact_audio_spans(words)
    assert "medical" in {f.kind for f in redaction.result.findings}
    assert [s.kind for s in redaction.spans] == ["email"]


def test_no_pii_means_no_spans() -> None:
    redaction = redact_audio_spans(_words("set a timer for twenty five minutes"))
    assert redaction.spans == ()


def test_raw_values_never_appear_in_returned_text(words) -> None:
    redaction = redact_audio_spans(words)
    exposed = " ".join(
        [repr(redaction), json.dumps(redaction.to_dict()), redaction.safe_transcript,
         *(repr(s) for s in redaction.spans)]
    ).lower()
    for value in RAW_VALUES:
        assert value not in exposed


# WAV writing


def test_bleep_changes_samples_inside_spans_only(words, wav, tmp_path) -> None:
    out = tmp_path / "out.wav"
    redaction = redact_audio_spans(words)
    applied = bleep_wav(wav, out, redaction)
    before, frame = _frames(wav)
    after, _ = _frames(out)
    assert len(before) == len(after)
    spans = _span_frames(applied)
    assert len(spans) == 2
    cursor = 0
    for s, e in spans:
        assert after[cursor * frame : s * frame] == before[cursor * frame : s * frame]
        inside_before, inside_after = before[s * frame : e * frame], after[s * frame : e * frame]
        changed = sum(a != b for a, b in zip(inside_after[::2], inside_before[::2], strict=True))
        assert changed > 0.9 * (e - s)
        cursor = e
    assert after[cursor * frame :] == before[cursor * frame :]


def test_beep_is_a_faded_sine_at_a_sane_level(wav, tmp_path) -> None:
    out = tmp_path / "out.wav"
    bleep_wav(wav, out, [(1.0, 2.0)], freq=1000, level=0.25)
    after, _ = _frames(out)
    samples = _samples(after[RATE * 2 : RATE * 4], 2)  # 1.0 s .. 2.0 s
    peak = max(abs(v) for v in samples)
    assert 0.24 * 32767 < peak <= 0.25 * 32767 + 1
    assert abs(samples[0]) < 0.05 * 32767 and abs(samples[-1]) < 0.05 * 32767  # fade, no click
    expected = [round(0.25 * 32767 * math.sin(2 * math.pi * 1000 * (RATE + n) / RATE))
                for n in range(100, 200)]
    assert samples[100:200] == expected


def test_silence_mode_zeroes_the_spans(words, wav, tmp_path) -> None:
    out = tmp_path / "out.wav"
    applied = bleep_wav(wav, out, redact_audio_spans(words), mode="silence")
    after, frame = _frames(out)
    for s, e in _span_frames(applied):
        assert set(after[s * frame : e * frame]) == {0}


@pytest.mark.parametrize("width", [1, 2, 3, 4])
@pytest.mark.parametrize("channels", [1, 2])
def test_sample_widths_and_channels(tmp_path, width, channels) -> None:
    src = tmp_path / "in.wav"
    _write_wav(src, 2.0, channels=channels, width=width)
    span = [(0.5, 1.0)]
    for mode in ("beep", "silence"):
        out = tmp_path / f"{mode}.wav"
        bleep_wav(src, out, span, mode=mode)
        before, frame = _frames(src)
        after, _ = _frames(out)
        s, e = _span_frames(span)[0]
        assert after[: s * frame] == before[: s * frame]
        assert after[e * frame :] == before[e * frame :]
        inside = _samples(after[s * frame : e * frame], width)
        if mode == "silence":
            assert set(inside) == {0}
        else:
            assert max(abs(v) for v in inside) > 0.2 * (2 ** (8 * width - 1))
            # Every channel carries the same beep.
            assert inside[0::channels] == inside[channels - 1 :: channels]


def test_spans_past_the_end_are_clamped(wav, tmp_path) -> None:
    applied = bleep_wav(wav, tmp_path / "out.wav", [(13.5, 99.0), (-1.0, 0.2)])
    assert applied == ((0.0, 0.2), (13.5, 14.0))


def test_streams_long_files_in_chunks(tmp_path) -> None:
    src = tmp_path / "long.wav"
    _write_wav(src, 20.0)  # 160k frames: several 64k-frame chunks
    out = tmp_path / "out.wav"
    bleep_wav(src, out, [(7.9, 8.4)], mode="silence")  # crosses the 65536-frame boundary
    before, frame = _frames(src)
    after, _ = _frames(out)
    s, e = _span_frames([(7.9, 8.4)])[0]
    assert set(after[s * frame : e * frame]) == {0}
    assert after[: s * frame] == before[: s * frame] and after[e * frame :] == before[e * frame :]


def test_refuses_to_overwrite_its_input(wav) -> None:
    with pytest.raises(ValueError):
        bleep_wav(wav, wav, [(0.0, 1.0)])


def test_bleep_file_with_given_words_needs_no_extras(words, wav, tmp_path, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    monkeypatch.setitem(sys.modules, "numpy", None)
    redaction = bleep_file(wav, tmp_path / "out.wav", words=words)
    assert [s.kind for s in redaction.spans] == ["payment_card", "email"]


def test_bleep_file_without_words_explains_the_extra(wav, tmp_path, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    with pytest.raises(ImportError, match=r"voicesafekit\[audio\]"):
        bleep_file(wav, tmp_path / "out.wav")


# Word parsing


def test_deepgram_response_parses_and_prefers_punctuated_words() -> None:
    response = {"results": {"channels": [{"alternatives": [{"words": [
        {"word": "my", "punctuated_word": "My", "start": 0.1, "end": 0.2},
        {"word": "email", "start": 0.3, "end": 0.6},
        {"word": "alex@example.com", "punctuated_word": "alex@example.com.",
         "start": 0.7, "end": 1.5},
    ]}]}]}}
    words = words_from_deepgram(response)
    assert words == [Word("My", 0.1, 0.2), Word("email", 0.3, 0.6),
                     Word("alex@example.com.", 0.7, 1.5)]
    assert load_words(response) == words
    sdk_like = SimpleNamespace(to_dict=lambda: response)
    assert words_from_deepgram(sdk_like) == words
    with pytest.raises(ValueError):
        words_from_deepgram({"results": {}})


def test_whisper_segments_parse_from_objects_and_json() -> None:
    seg = SimpleNamespace(words=[SimpleNamespace(word=" My", start=0.0, end=0.2),
                                 SimpleNamespace(word=" pin", start=0.2, end=0.5)])
    seg2 = SimpleNamespace(words=[SimpleNamespace(word=" is 4821.", start=0.5, end=1.4)])
    words = words_from_whisper(iter([seg, seg2]))
    assert [w.text for w in words] == [" My", " pin", " is 4821."]
    as_json = {"segments": [{"words": [{"word": " My", "start": 0.0, "end": 0.2}]}]}
    assert load_words(as_json) == [Word(" My", 0.0, 0.2)]
    assert load_words(as_json["segments"]) == [Word(" My", 0.0, 0.2)]
    with pytest.raises(ValueError, match="word_timestamps"):
        words_from_whisper([SimpleNamespace(words=None)])


def test_dict_words_parse_in_seconds_and_milliseconds() -> None:
    items = [{"text": "pin", "start": 100, "end": 400}, {"text": "4821", "start": 450, "end": 900}]
    assert words_from_dicts(items, unit="ms") == [Word("pin", 0.1, 0.4), Word("4821", 0.45, 0.9)]
    assert load_words({"words": [{"word": "hi", "start": 0, "end": 0.2}]}) == [Word("hi", 0, 0.2)]
    assert load_words([{"word": "hi", "start": 0, "end": 0.2}]) == [Word("hi", 0, 0.2)]
    with pytest.raises(ValueError):
        words_from_dicts([{"start": 0, "end": 1}])


def test_words_missing_times_borrow_from_neighbours() -> None:
    words = words_from_dicts([{"word": "pin", "start": 0.1, "end": 0.4},
                              {"word": "4821"},
                              {"word": "thanks", "start": 1.2, "end": 1.5}])
    assert words[1] == Word("4821", 0.4, 1.2)
    redaction = redact_audio_spans(words, padding=0.0)
    assert any(s.start <= 0.4 and s.end >= 1.2 for s in redaction.spans)


# CLI


def _cli_words_file(tmp_path, words, shape: str) -> Path:
    path = tmp_path / f"{shape}.json"
    rows = [{"word": w.text, "start": w.start, "end": w.end} for w in words]
    if shape == "deepgram":
        payload = {"results": {"channels": [{"alternatives": [{"words": rows}]}]}}
    elif shape == "segments":
        payload = {"segments": [{"words": rows}]}
    else:
        payload = rows
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.mark.parametrize("shape", ["list", "deepgram", "segments"])
def test_cli_bleep_with_words(tmp_path, words, wav, capsys, shape) -> None:
    out = tmp_path / "out.wav"
    code = main(["bleep", str(wav), "-o", str(out), "--words",
                 str(_cli_words_file(tmp_path, words, shape))])
    printed = capsys.readouterr().out
    assert code == 0
    assert out.exists() and _frames(out)[0] != _frames(wav)[0]
    assert "[payment number removed]" in printed and "[email removed]" in printed
    assert "Bleeped 2 span(s)" in printed
    assert "00:01.650 - 00:08.250  Payment card" in printed
    assert "00:09.650 - 00:12.650  Email address" in printed
    for value in RAW_VALUES:
        assert value not in printed.lower()


def test_cli_bleep_report_and_silence(tmp_path, words, wav, capsys) -> None:
    out = tmp_path / "out.wav"
    code = main(["bleep", str(wav), "-o", str(out), "--silence", "--padding", "0",
                 "--report", "--words", str(_cli_words_file(tmp_path, words, "list"))])
    printed = capsys.readouterr().out
    report = json.loads(printed)
    assert code == 0
    assert [s["kind"] for s in report["spans"]] == ["payment_card", "email"]
    assert report["spans"][0]["start"] == words[CARD_WORDS[0]].start
    assert report["decision"] in ("REVIEW", "BLOCK")
    for value in RAW_VALUES:
        assert value not in printed.lower()


def test_cli_bleep_without_words_or_extra_exits_with_hint(tmp_path, wav, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    with pytest.raises(SystemExit, match=r"voicesafekit\[audio\]"):
        main(["bleep", str(wav), "-o", str(tmp_path / "out.wav")])


def test_audio_span_dict_is_rounded() -> None:
    span = AudioSpan(0.123456, 1.987654, "pin", "PIN")
    assert span.to_dict() == {"start": 0.123, "end": 1.988, "kind": "pin", "label": "PIN"}
