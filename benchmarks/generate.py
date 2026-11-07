"""Generate SpokenPII: a synthetic benchmark of PII as speech-to-text writes it.

Every sample has a gold list of sensitive spans. The same underlying values are
rendered three ways:

* ``written``  - digits and symbols, how a careful STT engine formats speech
* ``spoken``   - words, how STT engines often emit speech ("four two four two",
                 "alex dot rivera at gmail dot com", "double oh")
* ``negative`` - ordinary assistant requests with no PII, many with numbers,
                 dates and words that trip naive detectors

All values are fake. Card numbers are Luhn-valid test numbers. Run:

    python benchmarks/generate.py > benchmarks/data/spokenpii.jsonl
"""

from __future__ import annotations

import json
import random

DIGIT_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
TEENS = ["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
         "seventeen", "eighteen", "nineteen"]
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]
ORDINALS = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth",
            "ninth", "tenth", "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth",
            "sixteenth", "seventeenth", "eighteenth", "nineteenth", "twentieth",
            "twenty first", "twenty second", "twenty third", "twenty fourth", "twenty fifth",
            "twenty sixth", "twenty seventh", "twenty eighth"]
FIRST = ["Alex", "Priya", "Daniel", "Fatima", "Tom", "Sara", "Omar", "Grace", "Liam", "Mei"]
LAST = ["Rivera", "Patel", "Hughes", "Khan", "Walker", "Nguyen", "Okafor", "Brennan"]
DOMAINS = ["gmail dot com", "outlook dot com", "yahoo dot co dot uk", "proton dot me",
           "icloud dot com", "company dot io"]


def luhn_number(rng: random.Random, prefix: str, length: int) -> str:
    digits = [int(c) for c in prefix]
    while len(digits) < length - 1:
        digits.append(rng.randint(0, 9))
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    digits.append((10 - total % 10) % 10)
    return "".join(map(str, digits))


def say_digits(rng: random.Random, digits: str, group: int = 4) -> str:
    """Render digits the way people read them out (with STT quirks)."""
    words: list[str] = []
    i = 0
    style = rng.choice(["plain", "plain", "oh", "double", "pairs"])
    while i < len(digits):
        d = digits[i]
        if style == "double" and i + 1 < len(digits) and digits[i + 1] == d:
            words.append("double " + ("oh" if d == "0" else DIGIT_WORDS[int(d)]))
            i += 2
            continue
        if style == "pairs" and i + 1 < len(digits) and d not in "01" and digits[i + 1] != "0":
            words.append(f"{TENS[int(d)]} {DIGIT_WORDS[int(digits[i + 1])]}")
            i += 2
            continue
        words.append("oh" if (d == "0" and style == "oh") else DIGIT_WORDS[int(d)])
        i += 1
    # Optional pauses between groups, as STT punctuation.
    if rng.random() < 0.3:
        out, count = [], 0
        for w in words:
            out.append(w)
            count += len(w.split()) if w.split()[0] not in ("double",) else 2
            if count >= group:
                out[-1] += ","
                count = 0
        words = out
    return " ".join(words).rstrip(",")


def say_year(year: int) -> str:
    hi, lo = divmod(year, 100)
    hi_w = TEENS[hi - 10] if hi < 20 else "twenty"
    if lo == 0:
        return f"{hi_w} hundred"
    if lo < 10:
        return f"{hi_w} oh {DIGIT_WORDS[lo]}"
    if lo < 20:
        return f"{hi_w} {TEENS[lo - 10]}"
    t, u = divmod(lo, 10)
    return f"{hi_w} {TENS[t]}" + (f" {DIGIT_WORDS[u]}" if u else "")


def sample(form, text_parts):
    """Build text and gold spans from [(str, entity_type_or_None), ...]."""
    text, entities = "", []
    for part, etype in text_parts:
        if etype:
            entities.append({"type": etype, "start": len(text), "end": len(text) + len(part)})
        text += part
    return {"form": form, "text": text, "entities": entities}


def make(rng: random.Random, kind: str, form: str) -> dict:
    spoken = form == "spoken"
    if kind == "card":
        num = luhn_number(rng, rng.choice(["4", "51", "37", "6011"]), 16)
        value = say_digits(rng, num) if spoken else " ".join(num[i:i + 4] for i in range(0, 16, 4))
        lead = rng.choice(["The long number on my card is ", "Charge it to my visa, ",
                           "My debit card number is ", "Use card "])
        tail = rng.choice([".", " please.", ""])
        return sample(form, [(lead, None), (value, "card"), (tail, None)])
    if kind == "ssn":
        num = f"{rng.randint(100, 665)}{rng.randint(10, 99)}{rng.randint(1000, 9999)}"
        value = say_digits(rng, num, 3) if spoken else f"{num[:3]}-{num[3:5]}-{num[5:]}"
        lead = rng.choice(["My social is ", "My social security number is ", "SSN ",
                           "For verification my social security is "])
        return sample(form, [(lead, None), (value, "ssn"), (".", None)])
    if kind == "phone":
        if rng.random() < 0.5:
            num = "07" + "".join(str(rng.randint(0, 9)) for _ in range(9))
            written = f"{num[:5]} {num[5:]}"
        else:
            num = f"{rng.randint(201, 989)}{rng.randint(200, 999)}{rng.randint(1000, 9999)}"
            written = f"({num[:3]}) {num[3:6]}-{num[6:]}"
        value = say_digits(rng, num, 3) if spoken else written
        lead = rng.choice(["Call me back on ", "My mobile is ", "You can text me at ",
                           "My number is "])
        tail = rng.choice([".", " anytime."])
        return sample(form, [(lead, None), (value, "phone"), (tail, None)])
    if kind == "email":
        first, last = rng.choice(FIRST).lower(), rng.choice(LAST).lower()
        joiner = rng.choice([" dot ", " underscore ", ""])
        domain = rng.choice(DOMAINS)
        if spoken:
            value = f"{first}{joiner}{last} at {domain}"
        else:
            sym = {" dot ": ".", " underscore ": "_", "": ""}[joiner]
            value = f"{first}{sym}{last}@{domain.replace(' dot ', '.')}"
        lead = rng.choice(["Send it to ", "My email is ", "Reply to ", "Use the address "])
        return sample(form, [(lead, None), (value, "email"), (".", None)])
    if kind == "pin":
        num = "".join(str(rng.randint(0, 9)) for _ in range(4))
        value = say_digits(rng, num) if spoken else num
        lead = rng.choice(["My pin is ", "The PIN number is ", "My card pin is "])
        return sample(form, [(lead, None), (value, "pin"), (".", None)])
    if kind == "otp":
        num = "".join(str(rng.randint(0, 9)) for _ in range(6))
        value = say_digits(rng, num, 3) if spoken else num
        lead = rng.choice(["The verification code is ", "The code they texted me is ",
                           "My one-time code is ", "The login code is "])
        return sample(form, [(lead, None), (value, "otp"), (".", None)])
    if kind == "dob":
        month = rng.randint(1, 12)
        day = rng.randint(1, 28)
        year = rng.randint(1950, 2005)
        if spoken:
            value = rng.choice([
                f"{MONTHS[month - 1]} {ORDINALS[day - 1]} {say_year(year)}",
                f"the {ORDINALS[day - 1]} of {MONTHS[month - 1]} {say_year(year)}",
            ])
        else:
            value = rng.choice([
                f"{MONTHS[month - 1].title()} {day}, {year}",
                f"{day:02d}/{month:02d}/{year}",
            ])
        lead = rng.choice(["I was born on ", "My date of birth is ", "My birthday is "])
        return sample(form, [(lead, None), (value, "dob"), (".", None)])
    if kind == "passport":
        num = "".join(str(rng.randint(0, 9)) for _ in range(9))
        value = say_digits(rng, num, 3) if spoken else num
        lead = rng.choice(["My passport number is ", "Passport "])
        return sample(form, [(lead, None), (value, "passport"), (".", None)])
    if kind == "name":
        value = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        lead = rng.choice(
            ["Hi, my name is ", "Hello, my name's ", "The booking is under, my name is "]
        )
        tail = rng.choice([".", " and I need help."])
        return sample(form, [(lead, None), (value, "name"), (tail, None)])
    raise ValueError(kind)


NEGATIVES = [
    "Set a timer for twenty five minutes.",
    "I need to build an emergency fund this year.",
    "Remind me to call Sue about dinner on Friday.",
    "What is the secret ingredient in a good carbonara?",
    "Help me reset my password please.",
    "Add a meeting on 2026-11-07 at the office.",
    "How many tokens does the model use?",
    "I have two kids and one dog.",
    "Oh no, I forgot my keys again.",
    "Play the top forty from nineteen ninety nine.",
    "Turn the heating up to twenty one degrees.",
    "Book a table for four at seven thirty.",
    "What is three hundred and twenty times four?",
    "My flight leaves at six fifteen tomorrow morning.",
    "Order two pizzas and a large coke.",
    "How far is it to the airport from here?",
    "Read me the news headlines.",
    "What year did the Berlin Wall fall?",
    "Convert one hundred dollars to pounds.",
    "Is it going to rain on the twenty first of may?",
    "I came first in the race last Sunday.",
    "Meet me at home after work.",
    "The password manager keeps crashing.",
    "Skip ahead thirty seconds.",
    "Call my mum.",
    "Set an alarm for five forty five.",
    "What is the population of London?",
    "Add milk, eggs and bread to my shopping list.",
    "I'll be there in ten minutes.",
    "Remind me in two weeks to renew the insurance.",
    "Who won the match four nil last night?",
    "The kids are seven and nine years old.",
    "Lower the volume to level three.",
    "Translate thank you very much into Spanish.",
    "How many calories are in two bananas?",
    "The room number is twelve on the second floor.",
    "Find a recipe that takes under thirty minutes.",
    "Start a workout for forty five minutes.",
    "I walked ten thousand steps today.",
    "What's on my calendar for the third?",
]


def main() -> None:
    rng = random.Random(20261107)
    kinds = ["card", "ssn", "phone", "email", "pin", "otp", "dob", "passport", "name"]
    rows = []
    for form in ("written", "spoken"):
        for kind in kinds:
            for _ in range(30):
                rows.append(make(rng, kind, form))
    for text in NEGATIVES:
        rows.append({"form": "negative", "text": text, "entities": []})
    for i, row in enumerate(rows):
        row["id"] = f"sp-{i:04d}"
        print(json.dumps(row, ensure_ascii=False))


if __name__ == "__main__":
    main()
