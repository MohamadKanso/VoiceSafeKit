"""Spoken-form normalisation for speech-to-text output.

Speech-to-text engines often write what people *say*, not what they *mean*:

    "my card is four two four two four two four two ..."
    "email me at alex dot rivera at gmail dot com"
    "call me on oh seven seven double oh nine ..."

Text-only PII detectors (regex or NER) miss all of these. This module rewrites
spoken numbers, spoken emails and spoken symbols into their written form and
keeps a character map back to the original transcript, so detections made on
the normalised text can be redacted in the original text.

Pure Python, no dependencies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

UNITS = {
    "zero": 0,
    "oh": 0,
    "o": 0,
    "nought": 0,
    "naught": 0,
    "nil": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
}
TEENS = {
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
TENS = {
    "twenty": 2,
    "thirty": 3,
    "forty": 4,
    "fourty": 4,
    "fifty": 5,
    "sixty": 6,
    "seventy": 7,
    "eighty": 8,
    "ninety": 9,
}
REPEATERS = {"double": 2, "triple": 3, "treble": 3}
# "oh" and "o" only count as zero when another number word is next to them.
WEAK_ZERO = {"oh", "o"}
TLDS = {
    "com", "org", "net", "io", "ai", "co", "uk", "us", "de", "fr", "es", "it", "nl",
    "edu", "gov", "dev", "app", "me", "info", "biz", "ca", "au", "ie", "ch", "eu",
    "in", "xyz", "tech", "email", "mail",
}

ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
    "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12,
    "thirteenth": 13, "fourteenth": 14, "fifteenth": 15, "sixteenth": 16,
    "seventeenth": 17, "eighteenth": 18, "nineteenth": 19, "twentieth": 20, "thirtieth": 30,
}
MONTHS = {
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
}

# A token is a word, a run of digits, or a single punctuation mark.
_TOKEN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?|\d+|[^\sA-Za-z\d]")


@dataclass(frozen=True)
class NormalizedText:
    """Normalised text plus a map from each normalised character to the original."""

    original: str
    text: str
    # For normalised char i, the original span it came from.
    src_start: tuple[int, ...]
    src_end: tuple[int, ...]

    @property
    def changed(self) -> bool:
        return self.text != self.original

    def to_original(self, start: int, end: int) -> tuple[int, int]:
        """Map a [start, end) span in the normalised text back to the original."""
        if start >= end:
            pos = self.src_start[start] if start < len(self.src_start) else len(self.original)
            return pos, pos
        return self.src_start[start], self.src_end[end - 1]


@dataclass
class _Tok:
    text: str
    start: int
    end: int

    @property
    def low(self) -> str:
        return self.text.lower()


def normalize_spoken(text: str) -> NormalizedText:
    """Rewrite spoken numbers, emails and symbols into written form."""
    tokens = [_Tok(m.group(0), m.start(), m.end()) for m in _TOKEN.finditer(text)]
    i = 0
    replaced: list[tuple[int, int, str, list[tuple[int, int]]]] = []

    while i < len(tokens):
        email = _match_spoken_email(tokens, i)
        if email:
            j, value = email
            span = (tokens[i].start, tokens[j - 1].end)
            replaced.append((span[0], span[1], value, [span] * len(value)))
            i = j
            continue
        ordinal = _match_date_ordinal(tokens, i)
        if ordinal:
            j, value = ordinal
            span = (tokens[i].start, tokens[j - 1].end)
            replaced.append((span[0], span[1], value, [span] * len(value)))
            i = j
            continue
        number = _match_number_run(tokens, i)
        if number:
            j, value, spans = number
            replaced.append((tokens[i].start, tokens[j - 1].end, value, spans))
            i = j
            continue
        i += 1

    if not replaced:
        n = len(text)
        return NormalizedText(text, text, tuple(range(n)), tuple(range(1, n + 1)))

    out: list[str] = []
    src_start: list[int] = []
    src_end: list[int] = []
    cursor = 0
    for start, end, value, spans in replaced:
        for k in range(cursor, start):
            out.append(text[k])
            src_start.append(k)
            src_end.append(k + 1)
        for ch, (s, e) in zip(value, spans, strict=True):
            out.append(ch)
            src_start.append(s)
            src_end.append(e)
        cursor = end
    for k in range(cursor, len(text)):
        out.append(text[k])
        src_start.append(k)
        src_end.append(k + 1)
    return NormalizedText(text, "".join(out), tuple(src_start), tuple(src_end))


# spoken dates


def _match_date_ordinal(tokens: list[_Tok], i: int) -> tuple[int, str] | None:
    """'march fourth' -> 'march 4th', 'twenty first of may' -> '21st of may'."""
    j = i
    value = 0
    if tokens[j].low in {"twenty", "thirty"} and j + 1 < len(tokens):
        nxt = tokens[j + 1].low
        if nxt in ORDINALS and ORDINALS[nxt] < 10:
            value = (20 if tokens[j].low == "twenty" else 30) + ORDINALS[nxt]
            j += 2
    if not value:
        if tokens[j].low not in ORDINALS:
            return None
        value = ORDINALS[tokens[j].low]
        j += 1
    if value > 31:
        return None
    prev_is_month = i > 0 and tokens[i - 1].low in MONTHS
    next_is_month = j < len(tokens) and tokens[j].low in MONTHS
    of_month = (
        j + 1 < len(tokens) and tokens[j].low == "of" and tokens[j + 1].low in MONTHS
    )
    if not (prev_is_month or next_is_month or of_month):
        return None
    suffix = "th"
    if value % 100 not in (11, 12, 13):
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return j, f"{value}{suffix}"


# number runs


def _number_value(tokens: list[_Tok], i: int) -> tuple[int, str] | None:
    """Read one spoken number unit at tokens[i]. Returns (tokens used, digits)."""
    tok = tokens[i]
    low = tok.low
    if tok.text.isdigit():
        return 1, tok.text
    if low in REPEATERS and i + 1 < len(tokens):
        nxt = tokens[i + 1]
        if nxt.low in UNITS:
            return 2, str(UNITS[nxt.low]) * REPEATERS[low]
        if nxt.text.isdigit() and len(nxt.text) == 1:
            return 2, nxt.text * REPEATERS[low]
        return None
    if low in TENS:
        nxt_low = tokens[i + 1].low if i + 1 < len(tokens) else ""
        if nxt_low in UNITS and nxt_low not in WEAK_ZERO:
            unit = UNITS[nxt_low]
            if unit != 0:
                return 2, f"{TENS[low]}{unit}"
        if (
            i + 2 < len(tokens)
            and tokens[i + 1].text == "-"
            and tokens[i + 2].low in UNITS
            and UNITS[tokens[i + 2].low] != 0
        ):
            return 3, f"{TENS[low]}{UNITS[tokens[i + 2].low]}"
        return 1, f"{TENS[low]}0"
    if low in TEENS:
        return 1, str(TEENS[low])
    if low in UNITS:
        return 1, str(UNITS[low])
    if low == "hundred":
        return 1, "00"
    return None


def _is_number_start(tokens: list[_Tok], i: int) -> bool:
    low = tokens[i].low
    if low in WEAK_ZERO:
        # "oh" is only a zero when the next real token is also a number word.
        return i + 1 < len(tokens) and _number_value(tokens, i + 1) is not None
    if low == "hundred":
        return False
    return _number_value(tokens, i) is not None


def _match_number_run(
    tokens: list[_Tok], i: int
) -> tuple[int, str, list[tuple[int, int]]] | None:
    """Collect a run of spoken/written digits such as 'four two 42 double oh'."""
    plus = False
    j = i
    if tokens[j].low == "plus" and j + 1 < len(tokens) and _is_number_start(tokens, j + 1):
        plus = True
        j += 1
    if not _is_number_start(tokens, j):
        return None

    digits: list[str] = []
    spans: list[tuple[int, int]] = []
    word_tokens = 0
    while j < len(tokens):
        tok = tokens[j]
        # Allow light separators inside a run: "four seven one, five five - eight".
        if tok.text in {",", "-", "."} and digits and j + 1 < len(tokens):
            if _number_value(tokens, j + 1) is not None and tokens[j + 1].low != "hundred":
                digits.append(" ")
                spans.append((tok.start, tok.end))
                j += 1
                continue
            break
        if tok.low in WEAK_ZERO and not digits and not _is_number_start(tokens, j):
            break
        read = _number_value(tokens, j)
        if read is None:
            break
        used, value = read
        if tokens[j].low == "hundred" and not digits:
            break
        span = (tokens[j].start, tokens[j + used - 1].end)
        if not tokens[j].text.isdigit():
            word_tokens += used
        digits.extend(value)
        spans.extend([span] * len(value))
        j += used

    while digits and digits[-1] == " ":
        digits.pop()
        spans.pop()
        j -= 1

    digit_count = sum(ch.isdigit() for ch in digits)
    # Only rewrite runs that contain spoken words and are long enough to matter.
    if word_tokens == 0 or digit_count < 3:
        return None
    value = "".join(digits)
    if plus:
        value = "+" + value
        spans.insert(0, (tokens[i].start, tokens[i].end))
    return j, value, spans


# spoken emails

_LOCAL_JOINERS = {
    "dot": ".",
    "period": ".",
    "underscore": "_",
    "dash": "-",
    "hyphen": "-",
}


def _email_word(tok: _Tok) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9]+", tok.text))


def _match_spoken_email(tokens: list[_Tok], i: int) -> tuple[int, str] | None:
    """Match 'alex dot rivera at gmail dot com' -> 'alex.rivera@gmail.com'."""
    if not _email_word(tokens[i]) or tokens[i].low in {"at", "dot"}:
        return None
    local = [tokens[i].text]
    j = i + 1
    while j + 1 < len(tokens) and tokens[j].low in _LOCAL_JOINERS and _email_word(tokens[j + 1]):
        local.append(_LOCAL_JOINERS[tokens[j].low])
        local.append(tokens[j + 1].text)
        j += 2
    if j >= len(tokens) or tokens[j].low not in {"at", "@"}:
        return None
    j += 1
    if j < len(tokens) and tokens[j].low in {"sign", "symbol"}:
        j += 1
    if j >= len(tokens) or not _email_word(tokens[j]):
        return None
    domain = [tokens[j].text]
    j += 1
    labels = 1
    while (
        j + 1 < len(tokens)
        and tokens[j].low in {"dot", "period", "."}
        and _email_word(tokens[j + 1])
    ):
        domain.append(".")
        domain.append(tokens[j + 1].text)
        labels += 1
        j += 2
    if labels < 2 or domain[-1].lower() not in TLDS:
        return None
    # Require at least one spoken joiner so "meet me at home" style text is never touched.
    joiners = {"dot", "period", "at", "underscore", "dash", "hyphen"}
    spoken = any(t.low in joiners for t in tokens[i:j])
    if not spoken:
        return None
    return j, ("".join(local) + "@" + "".join(domain)).lower()
