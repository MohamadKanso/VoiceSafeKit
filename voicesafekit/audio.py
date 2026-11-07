"""Audio redaction: bleep spoken PII out of a call recording, locally and for free.

Redacting the transcript still leaves the card number in the audio. This module
maps VoiceSafeKit findings back to word timestamps and overwrites those parts of
a WAV file with a beep (or silence).

The core path is standard library only:

    words = words_from_deepgram(response)          # or words_from_whisper / _dicts
    redaction = redact_audio_spans(words)          # findings -> time spans (seconds)
    bleep_wav("call.wav", "call.bleeped.wav", redaction)

``bleep_file`` / ``transcribe_words`` can produce the word timings themselves with
faster-whisper (``pip install "voicesafekit[audio]"``); that is the only optional part.

Limits: PCM WAV only (8/16/24/32-bit integer, any channel count). Files are
streamed in chunks, so length is not limited by memory. Timing accuracy is the
ASR's word-timestamp accuracy; ``padding`` widens each span to absorb drift.
"""

from __future__ import annotations

import math
import sys
import wave
from array import array
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from voicesafekit.engine import analyze_transcript
from voicesafekit.models import AnalysisResult
from voicesafekit.rules import INTENT_RULES

INTENT_KINDS = frozenset(rule.kind for rule in INTENT_RULES)
AUDIO_EXTRA_HINT = (
    'Word timestamps need faster-whisper: pip install "voicesafekit[audio]", '
    "or pass word timings yourself (words=... / --words words.json)."
)
_CHUNK_FRAMES = 65536


@dataclass(frozen=True)
class Word:
    """One recognised word and where it was spoken, in seconds."""

    text: str
    start: float
    end: float


@dataclass(frozen=True)
class AudioSpan:
    """A stretch of audio to bleep. Holds no transcript text, only times and labels.

    When nearby findings of different kinds merge into one span, ``kind`` and
    ``label`` list each of them (``"payment_card+pin"``, ``"Payment card, PIN"``).
    """

    start: float
    end: float
    kind: str
    label: str

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict[str, object]:
        return {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "kind": self.kind,
            "label": self.label,
        }


@dataclass(frozen=True)
class AudioRedaction:
    """Result of mapping PII findings onto word timings.

    ``result`` is the full ``AnalysisResult`` for the joined transcript. Like any
    ``AnalysisResult`` its ``redaction_map`` holds the raw values, so it is kept out
    of ``repr`` and ``to_dict``; everything else here is safe to log.
    """

    spans: tuple[AudioSpan, ...]
    safe_transcript: str
    result: AnalysisResult = field(repr=False)

    @property
    def decision(self) -> str:
        return self.result.decision

    def to_dict(self) -> dict[str, object]:
        return {
            "decision": self.result.decision,
            "safe_transcript": self.safe_transcript,
            "spans": [span.to_dict() for span in self.spans],
            "bleeped_seconds": round(sum(span.duration for span in self.spans), 3),
        }


# Building words from ASR output (duck-typed: no ASR library is imported here)


def words_from_whisper(segments: Iterable[Any]) -> list[Word]:
    """Words from faster-whisper (or openai-whisper) segments.

    Accepts segment objects with ``.words`` (``word``/``start``/``end`` attributes),
    as produced by ``model.transcribe(..., word_timestamps=True)``, or the same
    shape as dicts (``{"segments": [{"words": [...]}]}`` JSON).
    """
    items: list[Any] = []
    for segment in segments:
        seg_words = _get(segment, "words")
        if seg_words is None:
            raise ValueError("Segment has no word timings; transcribe with word_timestamps=True.")
        items.extend(seg_words)
    return words_from_dicts(items)


def words_from_deepgram(response: Any) -> list[Word]:
    """Words from a Deepgram pre-recorded response (dict, or SDK object with to_dict()).

    Reads ``results.channels[0].alternatives[0].words`` and prefers
    ``punctuated_word`` over ``word`` when present.
    """
    if not isinstance(response, Mapping) and hasattr(response, "to_dict"):
        response = response.to_dict()
    try:
        items = response["results"]["channels"][0]["alternatives"][0]["words"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(
            "Not a Deepgram response: expected results.channels[0].alternatives[0].words"
        ) from exc
    return words_from_dicts(items)


def words_from_dicts(items: Iterable[Any], *, unit: str = "s") -> list[Word]:
    """Words from a list of dicts or objects with text and start/end times.

    The text key may be ``punctuated_word``, ``word`` or ``text`` (first found wins).
    ``unit="ms"`` converts millisecond timings (AssemblyAI). Words missing a time
    (WhisperX leaves some numbers unaligned) borrow it from their neighbours.
    """
    scale = {"s": 1.0, "ms": 0.001}.get(unit)
    if scale is None:
        raise ValueError('unit must be "s" or "ms"')
    raw: list[tuple[str, float | None, float | None]] = []
    for item in items:
        if isinstance(item, Word):
            raw.append((item.text, item.start, item.end))
            continue
        text = None
        for key in ("punctuated_word", "word", "text"):
            text = _get(item, key)
            if text is not None:
                break
        if text is None:
            raise ValueError("Word entry has no 'word', 'punctuated_word' or 'text' field.")
        start, end = _get(item, "start"), _get(item, "end")
        raw.append(
            (
                str(text),
                None if start is None else float(start) * scale,
                None if end is None else float(end) * scale,
            )
        )
    return _fill_missing_times(raw)


def load_words(data: Any) -> list[Word]:
    """Words from parsed JSON in any supported shape.

    Deepgram responses, ``{"segments": [...]}`` (faster-whisper / openai-whisper /
    WhisperX), ``{"words": [...]}``, a list of segments, or a plain list of words.
    """
    if isinstance(data, Mapping):
        if "results" in data:
            return words_from_deepgram(data)
        if "segments" in data:
            return words_from_whisper(data["segments"])
        if "words" in data:
            return words_from_dicts(data["words"])
        raise ValueError("Unrecognised word JSON: expected results, segments or words.")
    if isinstance(data, Sequence) and not isinstance(data, (str, bytes)):
        if data and _get(data[0], "words") is not None:
            return words_from_whisper(data)
        return words_from_dicts(data)
    raise ValueError("Unrecognised word JSON: expected an object or a list.")


def _get(item: Any, key: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(key)
    return getattr(item, key, None)


def _fill_missing_times(raw: list[tuple[str, float | None, float | None]]) -> list[Word]:
    words: list[Word] = []
    for i, (text, start, end) in enumerate(raw):
        if start is None:
            start = words[-1].end if words else 0.0
        if end is None:
            nxt = next((s for _, s, _ in raw[i + 1 :] if s is not None), None)
            end = nxt if nxt is not None and nxt >= start else start
        words.append(Word(text=text, start=start, end=max(start, end)))
    return words


# Findings -> time spans


def redact_audio_spans(
    words: Iterable[Word], *, spoken: bool = True, padding: float = 0.15
) -> AudioRedaction:
    """Find PII in the spoken words and return the time spans that must be bleeped.

    Words are joined into one transcript (each word's character span recorded),
    analysed with ``analyze_transcript``, and every PII finding (intent findings
    such as "medical" are not bleeped) is mapped to the words it overlaps. Spans
    are padded by ``padding`` seconds each side, clamped at 0 and merged.
    """
    if padding < 0:
        raise ValueError("padding must be >= 0")
    kept = [w for w in words if w.text.strip()]
    pieces: list[str] = []
    offsets: list[tuple[int, int]] = []
    cursor = 0
    for word in kept:
        text = word.text.strip()
        # Whisper marks word boundaries with a leading space; a piece that starts with
        # punctuation and no space ("-55", ".rivera") belongs to the previous word.
        glue = bool(pieces) and not word.text[:1].isspace() and not word.text[:1].isalnum()
        if pieces and not glue:
            cursor += 1
            pieces.append(" ")
        offsets.append((cursor, cursor + len(text)))
        pieces.append(text)
        cursor += len(text)
    transcript = "".join(pieces)
    result = analyze_transcript(transcript, spoken=spoken)

    raw_spans: list[AudioSpan] = []
    for finding in result.findings:
        if finding.kind in INTENT_KINDS:
            continue
        hit = [
            kept[i]
            for i, (s, e) in enumerate(offsets)
            if s < finding.end and finding.start < e
        ]
        if not hit:
            continue
        raw_spans.append(
            AudioSpan(
                start=max(0.0, min(w.start for w in hit) - padding),
                end=max(w.end for w in hit) + padding,
                kind=finding.kind,
                label=finding.label,
            )
        )
    return AudioRedaction(
        spans=tuple(_merge_spans(raw_spans)),
        safe_transcript=result.safe_transcript,
        result=result,
    )


def _merge_spans(spans: list[AudioSpan]) -> list[AudioSpan]:
    merged: list[AudioSpan] = []
    for span in sorted(spans, key=lambda s: (s.start, s.end)):
        if merged and span.start <= merged[-1].end:
            last = merged[-1]
            merged[-1] = AudioSpan(
                start=last.start,
                end=max(last.end, span.end),
                kind=_join_unique(last.kind, span.kind, "+"),
                label=_join_unique(last.label, span.label, ", "),
            )
        else:
            merged.append(span)
    return merged


def _join_unique(left: str, right: str, sep: str) -> str:
    parts = left.split(sep)
    return left if right in parts else left + sep + right


# Writing the bleeped WAV (stdlib wave + array, streamed)


def bleep_wav(
    in_path: str | Path,
    out_path: str | Path,
    spans: AudioRedaction | Iterable[AudioSpan | tuple[float, float]],
    *,
    mode: str = "beep",
    freq: float = 1000.0,
    level: float = 0.25,
    fade: float = 0.005,
) -> tuple[tuple[float, float], ...]:
    """Copy a PCM WAV, replacing every span with a sine beep or silence.

    ``spans`` is an ``AudioRedaction``, ``AudioSpan`` objects or ``(start, end)``
    pairs in seconds. The beep is ``freq`` Hz at ``level`` of full scale (0.25 is
    about -12 dBFS) with a ``fade``-second ramp at each edge to avoid clicks.
    Samples outside the spans are copied byte for byte. Returns the spans actually
    applied, clamped to the file length, in seconds.
    """
    if mode not in ("beep", "silence"):
        raise ValueError('mode must be "beep" or "silence"')
    if not 0.0 <= level <= 1.0:
        raise ValueError("level must be between 0 and 1")
    in_path, out_path = Path(in_path), Path(out_path)
    if in_path.resolve() == out_path.resolve():
        raise ValueError("out_path must differ from in_path (the input is read while writing).")
    if isinstance(spans, AudioRedaction):
        spans = spans.spans
    pairs = sorted(
        (float(s.start), float(s.end)) if isinstance(s, AudioSpan) else (float(s[0]), float(s[1]))
        for s in spans
    )

    with wave.open(str(in_path), "rb") as src:
        channels, width, rate = src.getnchannels(), src.getsampwidth(), src.getframerate()
        nframes = src.getnframes()
        if width not in (1, 2, 3, 4):
            raise ValueError(f"Unsupported sample width: {width * 8}-bit")
        frame_spans = _frame_spans(pairs, rate, nframes)
        tone = _ToneWriter(mode, freq, level, fade, rate, channels, width)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out_path), "wb") as dst:
            dst.setnchannels(channels)
            dst.setsampwidth(width)
            dst.setframerate(rate)
            pos = 0
            while True:
                chunk = src.readframes(_CHUNK_FRAMES)
                if not chunk:
                    break
                count = len(chunk) // (channels * width)
                buf = bytearray(chunk)
                for s, e in frame_spans:
                    lo, hi = max(s, pos), min(e, pos + count)
                    if lo < hi:
                        a, b = (lo - pos) * channels * width, (hi - pos) * channels * width
                        buf[a:b] = tone.render(lo, hi, s, e)
                dst.writeframesraw(bytes(buf))
                pos += count
    return tuple((s / rate, e / rate) for s, e in frame_spans)


def _frame_spans(
    pairs: list[tuple[float, float]], rate: int, nframes: int
) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for start, end in pairs:
        s = min(nframes, max(0, math.floor(start * rate)))
        e = min(nframes, max(0, math.ceil(end * rate)))
        if e <= s:
            continue
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


class _ToneWriter:
    def __init__(
        self,
        mode: str,
        freq: float,
        level: float,
        fade: float,
        rate: int,
        channels: int,
        width: int,
    ) -> None:
        self.mode, self.freq, self.rate = mode, freq, rate
        self.channels, self.width = channels, width
        self.fade_frames = max(1, round(fade * rate))
        self.peak = (2 ** (8 * width - 1) - 1) * level

    def render(self, lo: int, hi: int, span_start: int, span_end: int) -> bytes:
        """Encoded samples for frames [lo, hi) of the span [span_start, span_end)."""
        if self.mode == "silence":
            values = [0] * ((hi - lo) * self.channels)
        else:
            step = 2.0 * math.pi * self.freq / self.rate
            values = []
            for n in range(lo, hi):
                ramp = min(1.0, (n - span_start + 1) / self.fade_frames,
                           (span_end - n) / self.fade_frames)
                values.extend([round(self.peak * ramp * math.sin(step * n))] * self.channels)
        return _encode(values, self.width)


def _encode(values: list[int], width: int) -> bytes:
    if width == 1:  # 8-bit WAV is unsigned, centred on 128
        return bytes(v + 128 for v in values)
    if width == 3:
        return b"".join(v.to_bytes(3, "little", signed=True) for v in values)
    code = "h" if width == 2 else ("i" if array("i").itemsize == 4 else "l")
    samples = array(code, values)
    if sys.byteorder == "big":
        samples.byteswap()
    return samples.tobytes()


# Optional: word timestamps from faster-whisper (the only non-stdlib path)


def transcribe_words(
    path: str | Path, *, model: Any = "base.en", language: str | None = "en"
) -> list[Word]:
    """Transcribe a WAV with faster-whisper and return its word timings.

    ``model`` is a model name or an already loaded ``WhisperModel``. The WAV is
    decoded with the standard library + numpy (mixed to mono, resampled to
    16 kHz), so faster-whisper's own audio decoder is not needed.
    """
    if isinstance(model, str):
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ImportError(AUDIO_EXTRA_HINT) from exc
        model = WhisperModel(model, device="cpu", compute_type="int8")
    audio = _read_wav_float(Path(path))
    segments, _info = model.transcribe(
        audio, language=language, beam_size=5, word_timestamps=True
    )
    return words_from_whisper(segments)


def _read_wav_float(path: Path) -> Any:
    try:
        import numpy as np
    except ImportError as exc:
        raise ImportError(AUDIO_EXTRA_HINT) from exc
    with wave.open(str(path), "rb") as wav:
        channels, width, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    if width == 1:
        data = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        data = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 3:
        b = np.frombuffer(frames, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        ints = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        ints = np.where(ints >= 1 << 23, ints - (1 << 24), ints)
        data = ints.astype(np.float32) / float(1 << 23)
    else:
        data = np.frombuffer(frames, dtype="<i4").astype(np.float32) / float(1 << 31)
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    if rate != 16000 and len(data):
        target = int(round(len(data) * 16000 / rate))
        data = np.interp(
            np.linspace(0, len(data) - 1, target), np.arange(len(data)), data
        ).astype(np.float32)
    return data


def bleep_file(
    in_path: str | Path,
    out_path: str | Path,
    *,
    words: Iterable[Word] | None = None,
    model: Any = "base.en",
    language: str | None = "en",
    spoken: bool = True,
    padding: float = 0.15,
    mode: str = "beep",
    freq: float = 1000.0,
) -> AudioRedaction:
    """Bleep the PII out of a WAV recording in one call.

    With ``words=None`` the file is transcribed with faster-whisper (needs
    ``pip install "voicesafekit[audio]"``); otherwise the given word timings are used
    and nothing beyond the standard library is needed.
    """
    if words is None:
        words = transcribe_words(in_path, model=model, language=language)
    redaction = redact_audio_spans(words, spoken=spoken, padding=padding)
    bleep_wav(in_path, out_path, redaction, mode=mode, freq=freq)
    return redaction


__all__ = [
    "AudioRedaction",
    "AudioSpan",
    "Word",
    "bleep_file",
    "bleep_wav",
    "load_words",
    "redact_audio_spans",
    "transcribe_words",
    "words_from_deepgram",
    "words_from_dicts",
    "words_from_whisper",
]
