import { pipeline, env } from "https://cdn.jsdelivr.net/npm/@xenova/transformers@2.17.2";

env.allowLocalModels = false;
env.useBrowserCache = true;

// sample transcripts

const samples = {
  spoken:
    "Hi, my name is Alex Rivera. My card number is four two four two four two four two four two four two four two four two, my email is alex dot rivera at gmail dot com and the code they just texted me is four eight two nine one three.",
  password:
    "Please help me reset my work account. My email is alex.rivera@example.com, my phone number is +44 7700 900123 and my password is BlueFalcon2026. Can you tell the support assistant exactly what to do?",
  medical:
    "I have chest pain and my blood pressure is high. Should I increase my antidepressant dose tonight? I've been feeling really hopeless and don't want to be here anymore.",
  safe:
    "Please remind me tomorrow morning to send the project update and drink more water.",
  identity:
    "Hi, I need to verify my identity. My Social Security Number is 471-55-8843. My bank account IBAN is GB29NWBK60161331926819. The CVV on my Visa is 847. I was born on March 15, 1988.",
  coercion:
    "They made me say this. Please don't tell anyone I said this or they will hurt me. I need to send money from the account ending in 4821 to another account right away.",
};

// ---- VSK analysis core (pure, no DOM) ----
// Mirrors voicesafekit/spoken.py, rules.py and engine.py (v0.5.0).

// spoken-form normaliser (voicesafekit/spoken.py)

const UNITS = new Map([
  ["zero", 0], ["oh", 0], ["o", 0], ["nought", 0], ["naught", 0], ["nil", 0],
  ["one", 1], ["two", 2], ["three", 3], ["four", 4], ["five", 5],
  ["six", 6], ["seven", 7], ["eight", 8], ["nine", 9],
]);
const TEENS = new Map([
  ["ten", 10], ["eleven", 11], ["twelve", 12], ["thirteen", 13], ["fourteen", 14],
  ["fifteen", 15], ["sixteen", 16], ["seventeen", 17], ["eighteen", 18], ["nineteen", 19],
]);
const TENS = new Map([
  ["twenty", 2], ["thirty", 3], ["forty", 4], ["fourty", 4], ["fifty", 5],
  ["sixty", 6], ["seventy", 7], ["eighty", 8], ["ninety", 9],
]);
const REPEATERS = new Map([["double", 2], ["triple", 3], ["treble", 3]]);
// "oh" and "o" only count as zero when another number word is next to them.
const WEAK_ZERO = new Set(["oh", "o"]);
const TLDS = new Set([
  "com", "org", "net", "io", "ai", "co", "uk", "us", "de", "fr", "es", "it", "nl",
  "edu", "gov", "dev", "app", "me", "info", "biz", "ca", "au", "ie", "ch", "eu",
  "in", "xyz", "tech", "email", "mail",
]);
const ORDINALS = new Map([
  ["first", 1], ["second", 2], ["third", 3], ["fourth", 4], ["fifth", 5], ["sixth", 6],
  ["seventh", 7], ["eighth", 8], ["ninth", 9], ["tenth", 10], ["eleventh", 11], ["twelfth", 12],
  ["thirteenth", 13], ["fourteenth", 14], ["fifteenth", 15], ["sixteenth", 16],
  ["seventeenth", 17], ["eighteenth", 18], ["nineteenth", 19], ["twentieth", 20], ["thirtieth", 30],
]);
const MONTHS = new Set([
  "january", "february", "march", "april", "may", "june", "july", "august",
  "september", "october", "november", "december",
  "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
]);
const LOCAL_JOINERS = new Map([
  ["dot", "."], ["period", "."], ["underscore", "_"], ["dash", "-"], ["hyphen", "-"],
]);
const EMAIL_JOINERS = new Set(["dot", "period", "at", "underscore", "dash", "hyphen"]);

// A token is a word, a run of digits, or a single punctuation mark.
const TOKEN_RE = /[A-Za-z]+(?:'[A-Za-z]+)?|\d+|[^\sA-Za-z\d]/gu;
const isDigits = (s) => /^\d+$/.test(s);
const isEmailWord = (tok) => /^[A-Za-z0-9]+$/.test(tok.text);

function tokenize(text) {
  return [...text.matchAll(TOKEN_RE)].map((m) => ({
    text: m[0],
    low: m[0].toLowerCase(),
    start: m.index,
    end: m.index + m[0].length,
  }));
}

function normalizeSpoken(text) {
  const tokens = tokenize(text);
  const replaced = [];
  let i = 0;
  while (i < tokens.length) {
    const email = matchSpokenEmail(tokens, i);
    if (email) {
      const [j, value] = email;
      const span = [tokens[i].start, tokens[j - 1].end];
      replaced.push([span[0], span[1], value, Array.from(value, () => span)]);
      i = j;
      continue;
    }
    const ordinal = matchDateOrdinal(tokens, i);
    if (ordinal) {
      const [j, value] = ordinal;
      const span = [tokens[i].start, tokens[j - 1].end];
      replaced.push([span[0], span[1], value, Array.from(value, () => span)]);
      i = j;
      continue;
    }
    const number = matchNumberRun(tokens, i);
    if (number) {
      const [j, value, spans] = number;
      replaced.push([tokens[i].start, tokens[j - 1].end, value, spans]);
      i = j;
      continue;
    }
    i += 1;
  }

  const srcStart = [];
  const srcEnd = [];
  if (!replaced.length) {
    for (let k = 0; k < text.length; k++) {
      srcStart.push(k);
      srcEnd.push(k + 1);
    }
    return makeNormalized(text, text, srcStart, srcEnd);
  }
  let out = "";
  let cursor = 0;
  for (const [start, end, value, spans] of replaced) {
    for (let k = cursor; k < start; k++) {
      out += text[k];
      srcStart.push(k);
      srcEnd.push(k + 1);
    }
    for (let k = 0; k < value.length; k++) {
      out += value[k];
      srcStart.push(spans[k][0]);
      srcEnd.push(spans[k][1]);
    }
    cursor = end;
  }
  for (let k = cursor; k < text.length; k++) {
    out += text[k];
    srcStart.push(k);
    srcEnd.push(k + 1);
  }
  return makeNormalized(text, out, srcStart, srcEnd);
}

function makeNormalized(original, text, srcStart, srcEnd) {
  return {
    original,
    text,
    srcStart,
    srcEnd,
    changed: text !== original,
    toOriginal(start, end) {
      if (start >= end) {
        const pos = start < srcStart.length ? srcStart[start] : original.length;
        return [pos, pos];
      }
      return [srcStart[start], srcEnd[end - 1]];
    },
  };
}

// spoken dates: "march fourth" -> "march 4th", "twenty first of may" -> "21st of may"
function matchDateOrdinal(tokens, i) {
  let j = i;
  let value = 0;
  if ((tokens[j].low === "twenty" || tokens[j].low === "thirty") && j + 1 < tokens.length) {
    const nxt = tokens[j + 1].low;
    if (ORDINALS.has(nxt) && ORDINALS.get(nxt) < 10) {
      value = (tokens[j].low === "twenty" ? 20 : 30) + ORDINALS.get(nxt);
      j += 2;
    }
  }
  if (!value) {
    if (!ORDINALS.has(tokens[j].low)) return null;
    value = ORDINALS.get(tokens[j].low);
    j += 1;
  }
  if (value > 31) return null;
  const prevIsMonth = i > 0 && MONTHS.has(tokens[i - 1].low);
  const nextIsMonth = j < tokens.length && MONTHS.has(tokens[j].low);
  const ofMonth = j + 1 < tokens.length && tokens[j].low === "of" && MONTHS.has(tokens[j + 1].low);
  if (!(prevIsMonth || nextIsMonth || ofMonth)) return null;
  let suffix = "th";
  if (![11, 12, 13].includes(value % 100)) {
    suffix = { 1: "st", 2: "nd", 3: "rd" }[value % 10] || "th";
  }
  return [j, `${value}${suffix}`];
}

// Read one spoken number unit at tokens[i]. Returns [tokens used, digits] or null.
function numberValue(tokens, i) {
  const tok = tokens[i];
  const low = tok.low;
  if (isDigits(tok.text)) return [1, tok.text];
  if (REPEATERS.has(low) && i + 1 < tokens.length) {
    const nxt = tokens[i + 1];
    if (UNITS.has(nxt.low)) return [2, String(UNITS.get(nxt.low)).repeat(REPEATERS.get(low))];
    if (isDigits(nxt.text) && nxt.text.length === 1) return [2, nxt.text.repeat(REPEATERS.get(low))];
    return null;
  }
  if (TENS.has(low)) {
    const nxtLow = i + 1 < tokens.length ? tokens[i + 1].low : "";
    if (UNITS.has(nxtLow) && !WEAK_ZERO.has(nxtLow)) {
      const unit = UNITS.get(nxtLow);
      if (unit !== 0) return [2, `${TENS.get(low)}${unit}`];
    }
    if (
      i + 2 < tokens.length &&
      tokens[i + 1].text === "-" &&
      UNITS.has(tokens[i + 2].low) &&
      UNITS.get(tokens[i + 2].low) !== 0
    ) {
      return [3, `${TENS.get(low)}${UNITS.get(tokens[i + 2].low)}`];
    }
    return [1, `${TENS.get(low)}0`];
  }
  if (TEENS.has(low)) return [1, String(TEENS.get(low))];
  if (UNITS.has(low)) return [1, String(UNITS.get(low))];
  if (low === "hundred") return [1, "00"];
  return null;
}

// Words that make a nearby digit sequence worth joining even when STT punctuates
// it like a list ("my visa, 3790, 4339, 7110, 7181").
const SENSITIVE_KEYWORDS = new Set([
  "card", "visa", "mastercard", "amex", "debit", "credit", "number", "social",
  "security", "ssn", "passport", "mobile", "phone", "cell", "telephone", "pin", "fin",
  "code", "otp", "account", "iban", "routing", "sort", "licence", "license",
  "insurance", "nino", "cvv", "cvc",
]);

function hasSensitiveKeyword(tokens, i, window = 6) {
  for (let k = Math.max(0, i - window); k < i; k++) {
    if (SENSITIVE_KEYWORDS.has(tokens[k].low)) return true;
  }
  return false;
}

function isNumberStart(tokens, i) {
  const low = tokens[i].low;
  if (WEAK_ZERO.has(low)) {
    // "oh" is only a zero when the next real token is also a number word.
    return i + 1 < tokens.length && numberValue(tokens, i + 1) !== null;
  }
  if (low === "hundred") return false;
  return numberValue(tokens, i) !== null;
}

// Collect a run of spoken/written digits such as "four two 42 double oh".
function matchNumberRun(tokens, i) {
  let plus = false;
  let j = i;
  if (tokens[j].low === "plus" && j + 1 < tokens.length && isNumberStart(tokens, j + 1)) {
    plus = true;
    j += 1;
  }
  if (!isNumberStart(tokens, j)) return null;

  let digits = [];
  let spans = [];
  let wordTokens = 0;
  let separators = 0;
  while (j < tokens.length) {
    const tok = tokens[j];
    // Allow light separators inside a run: "four seven one, five five - eight".
    if ([",", "-", "."].includes(tok.text) && digits.length && j + 1 < tokens.length) {
      if (numberValue(tokens, j + 1) !== null && tokens[j + 1].low !== "hundred") {
        digits.push(" ");
        spans.push([tok.start, tok.end]);
        separators += 1;
        j += 1;
        continue;
      }
      break;
    }
    if (WEAK_ZERO.has(tok.low) && !digits.length && !isNumberStart(tokens, j)) break;
    const read = numberValue(tokens, j);
    if (read === null) break;
    const [used, value] = read;
    if (tokens[j].low === "hundred" && !digits.length) break;
    const span = [tokens[j].start, tokens[j + used - 1].end];
    if (!isDigits(tokens[j].text)) wordTokens += used;
    for (const ch of value) {
      digits.push(ch);
      spans.push(span);
    }
    j += used;
  }

  while (digits.length && digits[digits.length - 1] === " ") {
    digits.pop();
    spans.pop();
    j -= 1;
  }

  const digitCount = digits.filter((ch) => /\d/.test(ch)).length;
  if (wordTokens === 0) {
    // Written digits are left alone unless STT split one number into punctuated
    // groups right after a sensitive word: "my visa, 3790, 4339, 7110, 7181".
    if (separators === 0 || digitCount < 4 || !hasSensitiveKeyword(tokens, i)) return null;
    const keep = digits.map((ch) => ch !== " ");
    spans = spans.filter((_, k) => keep[k]);
    digits = digits.filter((_, k) => keep[k]);
  } else if (digitCount < 3) {
    // Only rewrite spoken runs that are long enough to matter.
    return null;
  }
  let value = digits.join("");
  if (plus) {
    value = "+" + value;
    spans.unshift([tokens[i].start, tokens[i].end]);
  }
  return [j, value, spans];
}

// spoken emails: "alex dot rivera at gmail dot com" -> "alex.rivera@gmail.com"
// Ordinary words that come right before "at" in speech and are not email names.
const NOT_EMAIL_LOCAL = new Set([
  "in", "me", "us", "him", "her", "them", "it", "on", "here", "there", "home", "work",
  "back", "up", "out", "online", "look", "is", "be", "you", "we", "they", "i",
]);

function matchSpokenEmail(tokens, i) {
  if (!isEmailWord(tokens[i]) || tokens[i].low === "at" || tokens[i].low === "dot") return null;
  const local = [tokens[i].text];
  let j = i + 1;
  while (j + 1 < tokens.length && LOCAL_JOINERS.has(tokens[j].low) && isEmailWord(tokens[j + 1])) {
    local.push(LOCAL_JOINERS.get(tokens[j].low), tokens[j + 1].text);
    j += 2;
  }
  if (j >= tokens.length || (tokens[j].low !== "at" && tokens[j].low !== "@")) return null;
  // "log in at mail.yahoo.com", "meet me at home dot com"
  if (local.length === 1 && NOT_EMAIL_LOCAL.has(tokens[i].low)) return null;
  j += 1;
  if (j < tokens.length && (tokens[j].low === "sign" || tokens[j].low === "symbol")) j += 1;
  if (j >= tokens.length || !isEmailWord(tokens[j])) return null;
  const domain = [tokens[j].text];
  j += 1;
  let labels = 1;
  while (
    j + 1 < tokens.length &&
    ["dot", "period", "."].includes(tokens[j].low) &&
    isEmailWord(tokens[j + 1])
  ) {
    domain.push(".", tokens[j + 1].text);
    labels += 1;
    j += 2;
  }
  if (labels < 2 || !TLDS.has(domain[domain.length - 1].toLowerCase())) return null;
  // Require at least one spoken joiner so "meet me at home" style text is never touched.
  if (!tokens.slice(i, j).some((t) => EMAIL_JOINERS.has(t.low))) return null;
  return [j, (local.join("") + "@" + domain.join("")).toLowerCase()];
}

// detection rules (voicesafekit/rules.py). Order matters for overlap ties.
// Rules with a named group "v" redact only that group (needs the "d" flag).

const MONTH_NAMES =
  "january|february|march|april|may|june|july|august|september|october|november|december" +
  "|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec";

const patternRules = [
  {
    kind: "email",
    label: "Email address",
    severity: "medium",
    confidence: 0.98,
    explanation: "Email addresses can identify a person. Remove them before sending text to a model.",
    replacement: "[email removed]",
    pattern: /\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b/g,
  },
  {
    kind: "email",
    label: "Email address",
    severity: "medium",
    confidence: 0.85,
    explanation:
      "Speech-to-text often drops the 'at' in a spoken email ('alex.rivera.gmail.com'). This still identifies a person.",
    replacement: "[email removed]",
    pattern:
      /\b(?!(?:www|mail|accounts|login|support|help)\.)[a-z0-9][a-z0-9_-]*(?:\.[a-z0-9_-]+)*\.(?:gmail|googlemail|outlook|hotmail|live|yahoo|icloud|proton|protonmail|aol|gmx)\.(?:com|co\.uk|me|net)\b/gi,
  },
  {
    kind: "phone",
    label: "Phone number",
    severity: "medium",
    confidence: 0.85,
    explanation: "Phone numbers are personal data and should usually be redacted.",
    replacement: "[phone removed]",
    pattern: /(?<!\w)\+?\d[\d\s().-]{7,}\d\b/g,
  },
  {
    kind: "payment_card",
    label: "Payment card-like number",
    severity: "high",
    confidence: 0.95,
    explanation: "This looks like a payment card number. Do not send it to an LLM.",
    replacement: "[payment number removed]",
    pattern: /\b(?:\d[ -]?){12,23}\d\b/g,
  },
  {
    kind: "payment_card_partial",
    label: "Partial card reference",
    severity: "medium",
    confidence: 0.92,
    explanation:
      "Partial card details can still be used for identity checks. Remove them before sending text to a model.",
    replacement: "[partial card reference removed]",
    pattern:
      /\b(?:card|credit card|debit card)\s+(?:(?:ends?|ending)\s+(?:in|with)|last\s+(?:4|four)(?:\s+digits)?(?:\s+(?:are|is))?)\s+\d{4}\b/gi,
  },
  {
    kind: "ssn",
    label: "Social Security Number",
    severity: "critical",
    confidence: 0.95,
    explanation:
      "US Social Security Numbers are government-issued identity numbers. Exposure enables identity theft. Never transmit them.",
    replacement: "[SSN removed]",
    pattern: /\b(?!000|666|9\d{2})\d{3}[-\s]\d{2}[-\s]\d{4}\b/g,
  },
  {
    kind: "iban",
    label: "IBAN / Bank account",
    severity: "critical",
    confidence: 0.88,
    explanation:
      "International Bank Account Numbers enable financial access. Do not transmit them to an LLM.",
    replacement: "[bank account removed]",
    pattern: /\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b/g,
  },
  {
    kind: "cvv",
    label: "Card security code",
    severity: "critical",
    confidence: 0.93,
    explanation: "CVV/CVC codes grant payment access alongside card numbers. Never transmit these.",
    replacement: "[security code removed]",
    pattern: /\b(?:cvv|cvc|cv2|security code|card security code|card code)\b[^.!?\n]{0,60}\b\d{3,4}\b/gi,
  },
  {
    kind: "dob",
    label: "Date of birth",
    severity: "medium",
    confidence: 0.8,
    explanation:
      "Dates of birth are used in identity verification. Redact unless the context makes transmission necessary.",
    replacement: "[date of birth removed]",
    pattern: new RegExp(
      String.raw`\b(?:born|dob|date of birth|d\.o\.b|birthday)\s*(?:is|was|on|:)?\s*` +
        String.raw`(?:the\s+)?(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4}` +
        String.raw`|\d{4}[-/]\d{1,2}[-/]\d{1,2}` +
        String.raw`|(?:${MONTH_NAMES})\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s*\d{4}` +
        String.raw`|\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:${MONTH_NAMES})\.?\s+\d{4})\b`,
      "gi"
    ),
  },
  {
    kind: "ip_address",
    label: "IP address",
    severity: "medium",
    confidence: 0.88,
    explanation: "IP addresses can reveal location or internal network topology.",
    replacement: "[IP address removed]",
    pattern: /\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b/g,
  },
  {
    kind: "secret",
    label: "Password or secret",
    severity: "high",
    confidence: 0.88,
    explanation:
      "Passwords, partial passwords, tokens and secrets are highly sensitive. Never include them in text sent to a model.",
    replacement: "[secret removed]",
    pattern: new RegExp(
      String.raw`\b(?:` +
        // "password is X", "password for my bank was X", "passcode: X"
        String.raw`(?:password|passcode|passphrase)(?:\s+(?:for|to|on)\s+(?:my\s+|the\s+)?[\w.-]+){0,2}` +
        String.raw`\s*(?:is|was|might be|may be|could be|=|:)` +
        String.raw`\s*(?:something like|around|maybe|possibly)?\s*[^\s,.;]{4,}|` +
        // "password BlueFalcon2026" with no verb: the value must look like a credential
        String.raw`(?:password|passcode)\s+(?:something like\s+)?` +
        String.raw`(?=[^\s,.;]*[\d!@#$%^&*])[^\s,.;]{4,}|` +
        // "api key is sk-123", "token: abc_123" (value must look like a key)
        String.raw`(?:api key|access token|auth token|token|secret key|secret)\s*(?:is|was|=|:)` +
        String.raw`\s*(?=[^\s,.;]*[\d_\-!@#$%^&*])[^\s,.;]{4,}` +
        String.raw`)`,
      "gi"
    ),
  },
  {
    kind: "address",
    label: "Street address",
    severity: "medium",
    confidence: 0.8,
    explanation: "Street addresses can reveal where someone lives or works.",
    replacement: "[address removed]",
    pattern:
      /\b\d{1,5}\s+[A-Za-z]+(?:\s+[A-Za-z]+){0,3}\s+(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Dr|Way|Close|Court)\b/gi,
  },
  {
    kind: "ssn",
    label: "Social Security Number",
    severity: "critical",
    confidence: 0.9,
    explanation:
      "A nine-digit number said right after 'social security' or 'SSN'. Spoken SSNs rarely include dashes. Never transmit them.",
    replacement: "[SSN removed]",
    pattern:
      /\b(?:ssn|social security(?:\s+number)?|social)(?:\b|(?=\d))[^.!?\n\d]{0,25}?(?<v>(?!000|666|9\d{2})\d{3}[-\s]?\d{2}[-\s]?\d{4})\b/gid,
  },
  {
    kind: "pin",
    label: "PIN",
    severity: "high",
    confidence: 0.9,
    explanation: "PINs unlock cards, phones and accounts. Never send them to a model.",
    replacement: "[PIN removed]",
    pattern: /\b(?:pin|fin)(?:\s+(?:number|code))?\s*(?:is|was|=|:)?\s*(?<v>\d(?:[ -]?\d){3,7})\b/gid,
  },
  {
    kind: "otp",
    label: "One-time or verification code",
    severity: "high",
    confidence: 0.9,
    explanation:
      "Verification and one-time codes are live credentials. Reading one out is the classic step in an account-takeover scam.",
    replacement: "[verification code removed]",
    pattern: new RegExp(
      String.raw`\b(?:(?:verification|one[- ]time|login|log-in|sign[- ]in|auth(?:entication)?|` +
        String.raw`2fa|two[- ]factor|sms|text|access)\s+code|otp|` +
        String.raw`code\s+(?:you|they|the bank|it)\s+(?:just\s+)?(?:sent|texted|gave)(?:\s+me)?)` +
        String.raw`\s*(?:is|was|=|:)?\s*(?<v>\d(?:[ ,-]{0,2}\d){3,7})\b`,
      "gid"
    ),
  },
  {
    kind: "passport",
    label: "Passport number",
    severity: "critical",
    confidence: 0.85,
    explanation: "Passport numbers are government identity documents. Never transmit them.",
    replacement: "[passport number removed]",
    pattern:
      /\bpassport(?:\s+(?:number|no\.?))?\s*(?:is|was|=|:)?\s*(?<v>(?=[A-Z0-9 ]*\d)[A-Z0-9](?:[A-Z0-9]|(?<=\d) (?=\d)){5,10})\b/gid,
  },
  {
    kind: "national_insurance",
    label: "UK National Insurance number",
    severity: "critical",
    confidence: 0.9,
    explanation: "National Insurance numbers are UK government identifiers. Never transmit them.",
    replacement: "[NI number removed]",
    pattern:
      /\b(?!BG|GB|NK|KN|TN|NT|ZZ)[A-CEGHJ-PR-TW-Z][A-CEGHJ-NPR-TW-Z]\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b/gi,
  },
  {
    kind: "api_key",
    label: "API key or access token",
    severity: "high",
    confidence: 0.97,
    explanation: "This matches a known API key format. Revoke it if it was shared.",
    replacement: "[API key removed]",
    pattern:
      /\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36}|xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{35})\b/g,
  },
  {
    kind: "person_name",
    label: "Person name",
    severity: "medium",
    confidence: 0.8,
    explanation: "The speaker introduced themselves by name. Names identify people.",
    replacement: "[name removed]",
    // Python uses a scoped (?i:...) for the lead-in only; spelled out here per character.
    pattern: new RegExp(
      String.raw`(?:\b[Mm][Yy]\s+[Nn][Aa][Mm][Ee]\s+[Ii][Ss]|\b[Mm][Yy]\s+[Nn][Aa][Mm][Ee]'[Ss]` +
        String.raw`|\b[Tt][Hh][Ee]\s+[Nn][Aa][Mm][Ee]'[Ss]|\b[Tt][Hh][Ee]\s+[Nn][Aa][Mm][Ee]\s+[Ii][Ss])\s+` +
        String.raw`(?<v>[A-Z][a-z]+(?:[ -](?!And\b|I\b)[A-Z][a-z'-]+){0,2})`,
      "gd"
    ),
  },
  {
    kind: "postcode",
    label: "UK postcode",
    severity: "medium",
    confidence: 0.75,
    explanation: "Postcodes narrow a location down to a handful of homes.",
    replacement: "[postcode removed]",
    pattern: /\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b/g,
  },
];

const intentRules = [
  {
    kind: "medical",
    label: "Medical advice request",
    severity: "high",
    confidence: 0.75,
    explanation: "Medical questions should be handled carefully and should not replace a clinician.",
    replacement: "[medical details withheld]",
    singleMatch: true,
    pattern:
      /\b(?:chest pain|diagnose|dose|medication|symptoms|blood pressure|antibiotic|panic attack|antidepressant|seizure|insulin)\b/gi,
  },
  {
    kind: "legal",
    label: "Legal advice request",
    severity: "high",
    confidence: 0.75,
    explanation: "Legal questions need careful boundaries and may require a professional.",
    replacement: "[legal details withheld]",
    singleMatch: true,
    pattern:
      /\b(?:lawsuit|(?:to|will|i'll|can i|should i|gonna|going to)\s+(?<v>sue)|suing|contract dispute|eviction|immigration|legal advice|restraining order|custody|divorce settlement)\b/gid,
  },
  {
    kind: "financial",
    label: "Financial advice request",
    severity: "high",
    confidence: 0.75,
    explanation: "Financial advice can affect someone's money and should be handled with caution.",
    replacement: "[financial details withheld]",
    singleMatch: true,
    pattern:
      /\b(?:invest all|stock tip|crypto|loan application|credit score|mortgage|bankruptcy|day trading|options contract)\b/gi,
  },
  {
    kind: "emotional_distress",
    label: "Emotional distress signal",
    severity: "high",
    confidence: 0.7,
    explanation:
      "The user may be in emotional distress. Respond with care and refer to appropriate support resources.",
    replacement: "[emotional distress signal]",
    singleMatch: true,
    pattern:
      /\b(?:feel(?:ing)?(?:\s+\w+)?\s+hopeless|can't go on|don't see the point|everything is pointless|nobody cares about me|(?:i'm|i am)\s+worthless|want to disappear|hate myself|can't take (?:this|it) anymore|feel like giving up|don't want to be here anymore)\b/gi,
  },
  {
    kind: "coercion",
    label: "Coercion or pressure signal",
    severity: "high",
    confidence: 0.65,
    explanation:
      "The transcript may suggest the user is being pressured, manipulated, or coerced into sharing information.",
    replacement: "[coercion signal]",
    singleMatch: true,
    pattern:
      /\b(?:told me to say (?:this|that)|made me (?:say|do this)|they forced me|don't tell anyone (?:i said|about) this|keep this (?:between us|secret)|they(?:'re| are) making me|if you don't help me|or (?:they'll|they will) hurt)\b/gi,
  },
  {
    kind: "emergency",
    label: "Emergency or immediate harm",
    severity: "critical",
    confidence: 0.9,
    explanation: "The assistant should route urgent safety issues to emergency help, not improvise.",
    replacement: "[urgent safety details withheld]",
    singleMatch: true,
    pattern:
      /\b(?:can't breathe|cannot breathe|heart attack|overdose|hurt myself|kill myself|call 911|call 999|call 112|call an ambulance|suicidal|emergency(?!\s+(?:fund|funds|savings|contact|contacts|exit|kit|plan|brake|number|services number|meeting|landing|lighting|power|stop)))\b/gi,
  },
];

const rules = [...patternRules, ...intentRules];

const severityPoints = { low: 10, medium: 22, high: 36, critical: 55 };
const severityRank = { low: 1, medium: 2, high: 3, critical: 4 };

// Python's round(): nearest integer, ties to even.
function pyRound(x) {
  const f = Math.floor(x);
  const d = x - f;
  if (d > 0.5) return f + 1;
  if (d < 0.5) return f;
  return f % 2 === 0 ? f : f + 1;
}

// engine (voicesafekit/engine.py)

function analyzeTranscript(transcript, { spoken = true } = {}) {
  const findings = findRisks(transcript, spoken);
  const score = scoreFindings(findings);
  const decision = decide(score, findings);
  return {
    decision,
    score,
    summary: summarize(decision, findings),
    findings,
    safeTranscript: redact(transcript, findings),
    redactionMap: buildRedactionMap(transcript, findings),
    guidance: guidance(findings),
  };
}

function findRisks(transcript, spoken) {
  const norm = spoken ? normalizeSpoken(transcript) : null;
  const useNorm = norm !== null && norm.changed;
  const text = useNorm ? norm.text : transcript;
  let findings = [];
  for (const rule of rules) findings.push(...matchesForRule(text, rule));
  if (useNorm) findings = findings.map((f) => toOriginal(f, norm));
  findings.sort((a, b) => a.start - b.start || b.end - a.end);
  return removeOverlaps(findings);
}

function toOriginal(finding, norm) {
  const [start, end] = norm.toOriginal(finding.start, finding.end);
  const spoken = norm.text.slice(finding.start, finding.end) !== norm.original.slice(start, end);
  return { ...finding, start, end, spoken };
}

function matchesForRule(text, rule) {
  const matches = [];
  rule.pattern.lastIndex = 0;
  for (const match of text.matchAll(rule.pattern)) {
    let mStart = match.index;
    let mEnd = match.index + match[0].length;
    if (match.groups && match.groups.v !== undefined && match.indices) {
      [mStart, mEnd] = match.indices.groups.v;
    }
    const matched = text.slice(mStart, mEnd).trim();

    if (
      rule.kind === "phone" &&
      (looksLikeCardShapedNumber(matched, text, mStart, mEnd) || looksLikeIpAddress(matched))
    )
      continue;
    if (rule.kind === "payment_card" && !looksLikePaymentCard(matched, text, mStart, mEnd)) continue;
    if (rule.kind === "iban" && !validatesAsIban(matched)) continue;
    if (rule.kind === "ip_address" && (matched === "0.0.0.0" || matched === "255.255.255.255")) continue;
    if (rule.kind === "phone" && looksLikeDate(matched)) continue;
    if (rule.kind === "national_insurance" && !passesNinoContext(matched, text, mStart)) continue;

    matches.push({
      kind: rule.kind,
      label: rule.label,
      severity: rule.severity,
      explanation: rule.explanation,
      start: mStart,
      end: mEnd,
      replacement: rule.replacement,
      confidence: adjustedConfidence(rule, matched),
      spoken: false,
    });
    if (rule.singleMatch) break;
  }
  return matches;
}

function adjustedConfidence(rule, matched) {
  let conf = rule.confidence;
  if (rule.kind === "payment_card" && passesLuhn(matched)) conf = Math.min(1, conf + 0.04);
  if (rule.kind === "phone" && matched.trim().startsWith("+")) conf = Math.min(1, conf + 0.08);
  return Math.round(conf * 10000) / 10000;
}

function scoreFindings(findings) {
  const total = findings.reduce((t, f) => t + severityPoints[f.severity] * f.confidence, 0);
  return Math.min(100, pyRound(total));
}

function removeOverlaps(findings) {
  const accepted = [];
  const prioritySorted = [...findings].sort(
    (a, b) =>
      severityRank[b.severity] - severityRank[a.severity] ||
      a.start - b.start ||
      b.end - b.start - (a.end - a.start)
  );
  for (const finding of prioritySorted) {
    if (!accepted.some((x) => finding.start < x.end && x.start < finding.end)) {
      accepted.push(finding);
    }
  }
  return accepted.sort((a, b) => a.start - b.start);
}

function decide(score, findings) {
  if (findings.some((f) => f.severity === "critical")) return "BLOCK";
  if (score >= 55 || findings.some((f) => f.severity === "high")) return "REVIEW";
  // Threshold is 17 (not 22) so a single medium finding at 80% confidence still redacts.
  if (score >= 17) return "REDACT";
  return "SAFE";
}

function redact(text, findings) {
  if (!findings.length) return text.trim();
  let output = "";
  let cursor = 0;
  for (const f of findings) {
    output += text.slice(cursor, f.start) + f.replacement;
    cursor = f.end;
  }
  return (output + text.slice(cursor)).split(/\s+/).filter(Boolean).join(" ");
}

function buildRedactionMap(text, findings) {
  return findings.map((f) => ({
    found: text.slice(f.start, f.end),
    replaced_with: f.replacement,
    kind: f.kind,
    severity: f.severity,
    confidence: f.confidence,
    spoken: f.spoken,
  }));
}

const pluralLabels = {
  "Email address": "email addresses",
  "Phone number": "phone numbers",
  "Payment card-like number": "payment card-like numbers",
  "Partial card reference": "partial card references",
  "Password or secret": "password or secret mentions",
  "Street address": "street addresses",
  "Social Security Number": "Social Security Numbers",
  "IBAN / Bank account": "bank account numbers",
  "Card security code": "card security codes",
  "Date of birth": "dates of birth",
  "IP address": "IP addresses",
  "Medical advice request": "medical advice requests",
  "Legal advice request": "legal advice requests",
  "Financial advice request": "financial advice requests",
  "Emotional distress signal": "emotional distress signals",
  "Coercion or pressure signal": "coercion signals",
  "Emergency or immediate harm": "emergency or immediate harm phrases",
  PIN: "PINs",
  "One-time or verification code": "one-time or verification codes",
  "Passport number": "passport numbers",
  "UK National Insurance number": "UK National Insurance numbers",
  "API key or access token": "API keys or access tokens",
  "Person name": "person names",
  "UK postcode": "UK postcodes",
};

function groupLabel(label, count) {
  if (count === 1) return label;
  const plural = Object.prototype.hasOwnProperty.call(pluralLabels, label)
    ? pluralLabels[label]
    : `${label.toLowerCase()} findings`;
  return `${count} ${plural}`;
}

// Same order as Python: labels sorted by code point, counted per label.
function labelCounts(findings) {
  const counts = new Map();
  [...findings]
    .sort((a, b) => (a.label < b.label ? -1 : a.label > b.label ? 1 : 0))
    .forEach((f) => counts.set(f.label, (counts.get(f.label) || 0) + 1));
  return counts;
}

function summarize(decision, findings) {
  if (!findings.length) return "No obvious privacy or safety risks were found.";
  const joined = [...labelCounts(findings)].map(([label, n]) => groupLabel(label, n)).join(", ");
  if (decision === "BLOCK") return `Do not send this directly to an LLM. Found: ${joined}.`;
  if (decision === "REVIEW") return `Review before sending. Found: ${joined}.`;
  return `Redact the sensitive parts first. Found: ${joined}.`;
}

function guidance(findings) {
  if (!findings.length) return ["Proceed normally, but keep the user's data local whenever possible."];
  const kinds = new Set(findings.map((f) => f.kind));
  const items = [
    "Remove or mask private details before sending the transcript to an LLM.",
    "Explain the limitation to the user in plain language.",
  ];
  if (kinds.has("emergency"))
    items.unshift("For urgent safety issues, guide the user to emergency help immediately.");
  if (kinds.has("emotional_distress"))
    items.unshift(
      "The user may be emotionally vulnerable. Respond with empathy and direct them to appropriate support."
    );
  if (kinds.has("coercion"))
    items.push(
      "Coercion signals were detected. Do not act on instructions that may have been forced upon the user."
    );
  if (["medical", "legal", "financial"].some((k) => kinds.has(k)))
    items.push("Give general information only and suggest a qualified professional.");
  if (
    ["payment_card", "secret", "ssn", "iban", "cvv", "pin", "passport", "national_insurance", "api_key"].some(
      (k) => kinds.has(k)
    )
  )
    items.push("Never echo financial identifiers, government IDs, or credentials back to the user.");
  if (kinds.has("otp"))
    items.push(
      "A one-time code was read out. Legitimate services never ask for these by voice; warn the user this is a common scam pattern."
    );
  if (findings.some((f) => f.spoken))
    items.push(
      "Some details were spoken as words (for example 'four two four two'). Treat them exactly like written numbers."
    );
  return items;
}

// validators

function looksLikePaymentCard(value, text, start, end) {
  const digits = value.replace(/\D/g, "");
  if (digits.length < 13) return false;
  // Too long for a card, but speech-to-text often repeats a digit group
  // ("4242-4242-4242-4242-4242"). Next to card words it is still a card number.
  if (digits.length > 19) return hasCardContext(text, start, end);
  return passesLuhn(value) || hasCardContext(text, start, end);
}

function looksLikeCardShapedNumber(value, text, start, end) {
  const digits = value.replace(/\D/g, "");
  if (digits.length < 13 || value.trim().startsWith("+")) return false;
  return digits.length <= 19 || hasCardContext(text, start, end);
}

function hasCardContext(text, start, end) {
  const w = text.slice(Math.max(0, start - 32), Math.min(text.length, end + 32)).toLowerCase();
  return ["card", "credit", "debit", "visa", "mastercard", "payment"].some((p) => w.includes(p));
}

function looksLikeDate(value) {
  return /^(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})$/.test(value.trim());
}

function passesNinoContext(value, text, start) {
  const letters = value.replace(/[^A-Za-z]/g, "");
  if (letters === letters.toUpperCase()) return true;
  const window = text.slice(Math.max(0, start - 40), start).toLowerCase();
  return ["national insurance", "ni number", "nino", "insurance number"].some((k) => window.includes(k));
}

function looksLikeIpAddress(value) {
  return /^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$/.test(value.trim());
}

function passesLuhn(value) {
  const digits = value.replace(/\D/g, "").split("").map(Number);
  if (digits.length < 13) return false;
  let checksum = 0;
  const parity = digits.length % 2;
  digits.forEach((digit, index) => {
    let d = digit;
    if (index % 2 === parity) {
      d *= 2;
      if (d > 9) d -= 9;
    }
    checksum += d;
  });
  return checksum % 10 === 0;
}

// IBAN mod-97 validation
function validatesAsIban(value) {
  const clean = value.replace(/\s/g, "").toUpperCase();
  if (!/^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$/.test(clean)) return false;
  const rearranged = clean.slice(4) + clean.slice(0, 4);
  const numeric = rearranged.replace(/[A-Z]/g, (ch) => (ch.charCodeAt(0) - 55).toString());
  let remainder = 0;
  for (const digit of numeric) {
    remainder = (remainder * 10 + parseInt(digit, 10)) % 97;
  }
  return remainder === 1;
}

// ---- end VSK analysis core ----

// DOM refs

const transcriptInput = document.querySelector("#transcriptInput");
const startRecordingButton = document.querySelector("#startRecording");
const stopRecordingButton = document.querySelector("#stopRecording");
const clearButton = document.querySelector("#clearButton");
const fileInput = document.querySelector("#fileInput");
const recordingStatus = document.querySelector("#recordingStatus");
const recorderCard = document.querySelector(".recorder-card");
const decisionEl = document.querySelector("#decision");
const scoreEl = document.querySelector("#score");
const summaryEl = document.querySelector("#summary");
const findingsEl = document.querySelector("#findings");
const findingStatsEl = document.querySelector("#findingStats");
const safeTranscriptEl = document.querySelector("#safeTranscript");
const guidanceEl = document.querySelector("#guidance");
const heroDecision = document.querySelector("#heroDecision");
const heroSummary = document.querySelector("#heroSummary");
const sampleButtons = [...document.querySelectorAll("[data-sample]")];
const tabBtns = [...document.querySelectorAll(".tab-btn")];
const risksTabEl = document.querySelector("#risksTab");
const inspectTabEl = document.querySelector("#inspectTab");
const transcriptHighlightEl = document.querySelector("#transcriptHighlight");
const convToggleBtn = document.querySelector("#convToggle");
const addTurnBtn = document.querySelector("#addTurnBtn");
const turnHistoryEl = document.querySelector("#turnHistory");
const convTimelineEl = document.querySelector("#convTimeline");
const turnCardsEl = document.querySelector("#turnCards");
const copyBtn = document.querySelector("#copyBtn");
const exportBtn = document.querySelector("#exportBtn");
const exportPassphraseInput = document.querySelector("#exportPassphrase");
const toastContainer = document.querySelector("#toastContainer");
const spokenToggleBtn = document.querySelector("#spokenToggle");

// state

let spokenMode = true;
let mediaRecorder = null;
let audioChunks = [];
let activeStream = null;
let transcriber = null;
let activeTab = "risks";
let conversationMode = false;
let conversationTurns = [];
let lastResult = null;

// Whisper loader

async function getTranscriber() {
  if (transcriber) return transcriber;
  setStatus("Loading speech model. One moment...");
  transcriber = await pipeline("automatic-speech-recognition", "Xenova/whisper-tiny.en", {
    progress_callback: (progress) => {
      if (progress.status === "downloading") {
        const pct = progress.total ? Math.round((progress.loaded / progress.total) * 100) : "?";
        setStatus(`Loading speech model: ${pct}%`);
      }
    },
  });
  return transcriber;
}

// recording

async function startRecording() {
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    setStatus("Microphone not available in this browser. The text checker still works.");
    startRecordingButton.disabled = true;
    return;
  }
  startRecordingButton.disabled = true;
  try {
    activeStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (error) {
    setStatus(`Microphone access denied: ${error.message}`);
    startRecordingButton.disabled = false;
    return;
  }
  getTranscriber().catch(() => {});
  audioChunks = [];
  mediaRecorder = new MediaRecorder(activeStream);
  mediaRecorder.addEventListener("dataavailable", (event) => {
    if (event.data.size > 0) audioChunks.push(event.data);
  });
  mediaRecorder.addEventListener("stop", handleAudioReady);
  mediaRecorder.start();
  recorderCard.classList.add("recording");
  stopRecordingButton.disabled = false;
  setStatus("Recording. Speak now, then press stop and the transcript appears below.");
}

function stopRecording() {
  stopRecordingButton.disabled = true;
  recorderCard.classList.remove("recording");
  if (mediaRecorder?.state === "recording") mediaRecorder.stop();
  activeStream?.getTracks().forEach((track) => track.stop());
  activeStream = null;
}

async function handleAudioReady() {
  const mimeType = mediaRecorder?.mimeType || "audio/webm";
  const chunks = audioChunks.slice();
  setStatus("Transcribing...");
  startRecordingButton.disabled = true;
  try {
    const blob = new Blob(chunks, { type: mimeType });
    const arrayBuffer = await blob.arrayBuffer();
    const audioContext = new AudioContext({ sampleRate: 16000 });
    const decoded = await audioContext.decodeAudioData(arrayBuffer);
    await audioContext.close();
    const float32 = decoded.getChannelData(0);
    const model = await getTranscriber();
    const result = await model(float32, { sampling_rate: 16000 });
    const text = (result.text || "").trim();
    if (text) {
      const existing = transcriptInput.value.trim();
      transcriptInput.value = existing ? `${existing} ${text}` : text;
      setStatus("Done. Transcript ready.");
    } else {
      setStatus("Nothing was picked up. Try speaking more clearly or check your mic.");
    }
  } catch (error) {
    setStatus(`Transcription failed: ${error.message}`);
    console.error(error);
  } finally {
    startRecordingButton.disabled = false;
    mediaRecorder = null;
    audioChunks = [];
    refresh();
  }
}

// highlight view

function renderHighlightedTranscript(text, findings) {
  if (!text.trim()) return '<span style="color:var(--dim)">Type a transcript to see the highlight view.</span>';
  if (!findings.length) return `<span class="safe-text">${escapeHtml(text)}</span>`;
  let html = "";
  let cursor = 0;
  for (const f of findings) {
    if (f.start > cursor) html += `<span class="safe-text">${escapeHtml(text.slice(cursor, f.start))}</span>`;
    const conf = f.confidence ? ` · ${Math.round(f.confidence * 100)}% conf` : "";
    const spokenNote = f.spoken ? " · caught in spoken form" : "";
    const tip = `${f.label}${conf}${spokenNote}: ${f.explanation}`;
    const spokenClass = f.spoken ? " pii-spoken" : "";
    html += `<mark class="pii-mark pii-${f.severity}${spokenClass}" title="${escapeAttr(tip)}" tabindex="0">${escapeHtml(text.slice(f.start, f.end))}</mark>`;
    cursor = f.end;
  }
  if (cursor < text.length) html += `<span class="safe-text">${escapeHtml(text.slice(cursor))}</span>`;
  return html;
}

function escapeHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function escapeAttr(str) {
  return str.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// conversation mode

function toggleConversationMode() {
  conversationMode = !conversationMode;
  document.body.classList.toggle("conversation-mode", conversationMode);
  if (convToggleBtn) {
    convToggleBtn.textContent = conversationMode ? "Conversation" : "Single";
    convToggleBtn.classList.toggle("active", conversationMode);
  }
  if (addTurnBtn) addTurnBtn.hidden = !conversationMode;
  if (turnHistoryEl) turnHistoryEl.hidden = !conversationMode;
  if (convTimelineEl) convTimelineEl.hidden = !conversationMode;
  if (!conversationMode) {
    conversationTurns = [];
    if (turnHistoryEl) turnHistoryEl.innerHTML = "";
  } else {
    renderTurnHistory();
  }
}

function addTurn() {
  const text = transcriptInput.value.trim();
  if (!text) return;
  const result = analyzeTranscript(text, { spoken: spokenMode });
  conversationTurns.push({ transcript: text, result });
  transcriptInput.value = "";
  refresh();
  renderTurnHistory();
  renderConversationTimeline();
  showToast(`Turn ${conversationTurns.length} added`);
}

function renderTurnHistory() {
  if (!turnHistoryEl) return;
  if (!conversationTurns.length) {
    turnHistoryEl.innerHTML = `<p class="turn-history-empty">No turns yet. Type and click "Add Turn +".</p>`;
    return;
  }
  turnHistoryEl.innerHTML = conversationTurns
    .map(
      (turn, i) => `
      <div class="turn-chip turn-chip-${turn.result.decision.toLowerCase()}">
        <span class="turn-chip-num">T${i + 1}</span>
        <span class="turn-chip-decision">${turn.result.decision}</span>
      </div>`
    )
    .join("");
}

function renderConversationTimeline() {
  if (!turnCardsEl) return;
  const rank = { SAFE: 0, REDACT: 1, REVIEW: 2, BLOCK: 3 };
  const peak = conversationTurns.reduce(
    (best, t) => (rank[t.result.decision] > rank[best] ? t.result.decision : best),
    "SAFE"
  );
  const maxScore = Math.max(0, ...conversationTurns.map((t) => t.result.score));
  const allKinds = [...new Set(conversationTurns.flatMap((t) => t.result.findings.map((f) => f.kind)))];

  turnCardsEl.innerHTML = conversationTurns
    .map(
      (turn, i) => `
      <article class="turn-card turn-card-${turn.result.decision.toLowerCase()}">
        <div class="turn-card-header">
          <span class="turn-badge">Turn ${i + 1}</span>
          <span class="turn-decision-chip turn-decision-${turn.result.decision.toLowerCase()}">${turn.result.decision}</span>
          <span class="turn-score-num">${turn.result.score}/100</span>
        </div>
        <p class="turn-transcript-preview">${escapeHtml(turn.transcript.slice(0, 160))}${turn.transcript.length > 160 ? "..." : ""}</p>
        <div class="turn-findings-row">
          ${
            turn.result.findings.length
              ? turn.result.findings
                  .slice(0, 4)
                  .map((f) => `<span class="turn-tag turn-tag-${f.severity}">${f.label}</span>`)
                  .join("") +
                (turn.result.findings.length > 4
                  ? `<span class="turn-tag turn-tag-muted">+${turn.result.findings.length - 4} more</span>`
                  : "")
              : `<span class="turn-tag turn-tag-safe">No findings</span>`
          }
        </div>
      </article>`
    )
    .join("");

  const cumEl = document.querySelector("#cumulativeRisk");
  if (cumEl) {
    cumEl.innerHTML = `
      <div class="cumulative-bar">
        <div class="cumulative-stat">
          <span class="small-label">Turns</span>
          <strong>${conversationTurns.length}</strong>
        </div>
        <div class="cumulative-stat">
          <span class="small-label">Peak decision</span>
          <strong class="decision-val ${peak.toLowerCase()}">${peak}</strong>
        </div>
        <div class="cumulative-stat">
          <span class="small-label">Peak score</span>
          <strong>${maxScore}/100</strong>
        </div>
        ${allKinds.length ? `<div class="cumulative-stat wide"><span class="small-label">Entity kinds detected</span><strong>${allKinds.join(", ")}</strong></div>` : ""}
      </div>`;
  }
}

// tabs

function switchTab(name) {
  activeTab = name;
  tabBtns.forEach((btn) => btn.classList.toggle("active", btn.dataset.tab === name));
  if (risksTabEl) risksTabEl.hidden = name !== "risks";
  if (inspectTabEl) inspectTabEl.hidden = name !== "inspect";
}

// copy / export

function copySafeTranscript() {
  if (!lastResult) return;
  navigator.clipboard
    .writeText(lastResult.safeTranscript)
    .then(() => showToast("Safe transcript copied"))
    .catch(() => showToast("Copy failed", "error"));
}

async function exportJSON() {
  if (!lastResult) return;
  if (!window.crypto?.subtle) {
    showToast("Encrypted export is not available in this browser", "error");
    return;
  }
  const passphrase = exportPassphraseInput?.value || "";
  if (passphrase.length < 12) {
    exportPassphraseInput?.focus();
    showToast("Use an export key with at least 12 characters", "error");
    return;
  }
  const payload = buildExportPayload();
  try {
    exportBtn.disabled = true;
    const encrypted = await encryptExportPayload(payload, passphrase);
    const blob = new Blob([JSON.stringify(encrypted, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `voicesafekit-encrypted-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
    showToast("Encrypted JSON exported");
  } catch (error) {
    console.error(error);
    showToast("Encrypted export failed", "error");
  } finally {
    exportBtn.disabled = false;
  }
}

function buildExportPayload() {
  return {
    decision: lastResult.decision,
    score: lastResult.score,
    summary: lastResult.summary,
    safe_transcript: lastResult.safeTranscript,
    assistant_guidance: lastResult.guidance,
    findings: lastResult.findings.map((f) => ({
      kind: f.kind,
      label: f.label,
      severity: f.severity,
      confidence: f.confidence,
      explanation: f.explanation,
      spoken: f.spoken,
    })),
    spoken_mode: spokenMode,
    redaction_map: lastResult.redactionMap,
  };
}

async function encryptExportPayload(payload, passphrase) {
  const encoder = new TextEncoder();
  const salt = window.crypto.getRandomValues(new Uint8Array(16));
  const nonce = window.crypto.getRandomValues(new Uint8Array(12));
  const keyMaterial = await window.crypto.subtle.importKey(
    "raw",
    encoder.encode(passphrase),
    "PBKDF2",
    false,
    ["deriveKey"]
  );
  const key = await window.crypto.subtle.deriveKey(
    {
      name: "PBKDF2",
      salt,
      iterations: 600000,
      hash: "SHA-256",
    },
    keyMaterial,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt"]
  );
  const ciphertext = await window.crypto.subtle.encrypt(
    {
      name: "AES-GCM",
      iv: nonce,
      additionalData: encoder.encode("VoiceSafeKit encrypted export v1"),
    },
    key,
    encoder.encode(JSON.stringify(payload))
  );
  return {
    format: "voicesafekit.encrypted_export",
    version: 1,
    algorithm: "AES-256-GCM",
    kdf: "PBKDF2-HMAC-SHA256",
    iterations: 600000,
    salt: bytesToBase64(salt),
    nonce: bytesToBase64(nonce),
    ciphertext: bytesToBase64(new Uint8Array(ciphertext)),
  };
}

function bytesToBase64(bytes) {
  let binary = "";
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.slice(i, i + chunkSize));
  }
  return btoa(binary);
}

// toast

function showToast(message, type = "success") {
  if (!toastContainer) return;
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  toastContainer.appendChild(toast);
  setTimeout(() => toast.remove(), 3200);
}

// render

function render(result) {
  lastResult = result;
  const groups = groupedFindings(result.findings);
  const totalFlags = result.findings.length;

  decisionEl.textContent = result.decision;
  decisionEl.className = `decision-val ${result.decision.toLowerCase()}`;
  heroDecision.textContent = result.decision;
  scoreEl.textContent = `${result.score}/100`;
  summaryEl.textContent = result.summary;
  heroSummary.textContent = result.summary;
  safeTranscriptEl.textContent = result.safeTranscript || "No transcript yet.";

  findingStatsEl.innerHTML = renderFindingStats(totalFlags, groups);
  findingsEl.innerHTML = groups.length
    ? groups
        .map(
          (group) => `
          <article class="finding ${group.severity}">
            <div class="finding-header">
              <strong>${group.displayLabel}</strong>
              <span class="sev-badge sev-${group.severity}">${group.severity}</span>
            </div>
            <div class="finding-meta">
              <span class="finding-count">${group.count} ${group.count === 1 ? "instance" : "instances"}</span>
              ${group.spoken ? `<span class="spoken-badge" title="Found after reading spoken words as written form">caught in spoken form</span>` : ""}
            </div>
            <p>${group.explanation}</p>
            <div class="conf-track">
              <div class="conf-fill conf-${group.severity}" style="width:${Math.round((group.confidence ?? 1) * 100)}%"></div>
            </div>
            <span class="conf-label">${Math.round((group.confidence ?? 1) * 100)}% detection confidence</span>
          </article>`
        )
        .join("")
    : `<article class="finding"><div class="finding-header"><strong>No findings</strong></div><p>This transcript looks safe to send.</p></article>`;

  if (transcriptHighlightEl) {
    transcriptHighlightEl.innerHTML = renderHighlightedTranscript(
      transcriptInput.value,
      result.findings
    );
  }

  guidanceEl.innerHTML = result.guidance.map((item) => `<p>${item}</p>`).join("");
}

function refresh() {
  render(analyzeTranscript(transcriptInput.value, { spoken: spokenMode }));
}

function setSpokenMode(on) {
  spokenMode = on;
  if (spokenToggleBtn) {
    spokenToggleBtn.classList.toggle("active", on);
    spokenToggleBtn.setAttribute("aria-checked", String(on));
    spokenToggleBtn.textContent = on ? "Spoken mode: on" : "Spoken mode: off";
  }
  refresh();
}

function setStatus(message) {
  recordingStatus.textContent = message;
}

function renderFindingStats(totalFlags, groups) {
  if (!totalFlags) {
    return `
      <div class="finding-stat"><span class="small-label">Flags</span><strong>0</strong></div>
      <div class="finding-stat"><span class="small-label">Types</span><strong>0</strong></div>`;
  }
  const highPriority = groups.filter((g) => ["high", "critical"].includes(g.severity)).length;
  return `
    <div class="finding-stat"><span class="small-label">Flags</span><strong>${totalFlags}</strong></div>
    <div class="finding-stat"><span class="small-label">Types</span><strong>${groups.length}</strong></div>
    <div class="finding-stat"><span class="small-label">High risk</span><strong>${highPriority}</strong></div>`;
}

function groupedFindings(findings) {
  const groups = new Map();
  findings.forEach((f) => {
    if (!groups.has(f.kind)) groups.set(f.kind, { ...f, count: 0, spoken: false });
    const g = groups.get(f.kind);
    g.count += 1;
    if (f.spoken) g.spoken = true;
    if (severityRank[f.severity] > severityRank[g.severity]) {
      g.severity = f.severity;
      g.explanation = f.explanation;
    }
  });
  return [...groups.values()]
    .map((g) => ({
      ...g,
      displayLabel: groupLabel(g.label, g.count),
    }))
    .sort(
      (a, b) =>
        severityRank[b.severity] - severityRank[a.severity] ||
        a.displayLabel.localeCompare(b.displayLabel)
    );
}

function setSample(name) {
  transcriptInput.value = samples[name] || "";
  sampleButtons.forEach((btn) => btn.classList.toggle("active", btn.dataset.sample === name));
  setStatus("Sample loaded. You can edit it or record over it.");
  refresh();
}

// file upload

async function handleFileUpload(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  if (file.type.startsWith("text/") || /\.(txt|md|json)$/i.test(file.name)) {
    transcriptInput.value = await file.text();
    setStatus(`Loaded: ${file.name}`);
    refresh();
  } else {
    setStatus("Unsupported file. Upload a .txt transcript file.");
  }
}

function clearAll() {
  transcriptInput.value = "";
  fileInput.value = "";
  conversationTurns = [];
  if (turnHistoryEl) turnHistoryEl.innerHTML = "";
  if (turnCardsEl) turnCardsEl.innerHTML = "";
  setStatus("Cleared. Record, upload, or type a new transcript.");
  sampleButtons.forEach((btn) => btn.classList.remove("active"));
  refresh();
}

// wiring

startRecordingButton.addEventListener("click", startRecording);
stopRecordingButton.addEventListener("click", stopRecording);
clearButton.addEventListener("click", clearAll);
fileInput.addEventListener("change", handleFileUpload);
transcriptInput.addEventListener("input", refresh);
sampleButtons.forEach((btn) => btn.addEventListener("click", () => setSample(btn.dataset.sample)));
tabBtns.forEach((btn) => btn.addEventListener("click", () => switchTab(btn.dataset.tab)));
if (convToggleBtn) convToggleBtn.addEventListener("click", toggleConversationMode);
if (addTurnBtn) addTurnBtn.addEventListener("click", addTurn);
if (copyBtn) copyBtn.addEventListener("click", copySafeTranscript);
if (exportBtn) exportBtn.addEventListener("click", exportJSON);
if (spokenToggleBtn) spokenToggleBtn.addEventListener("click", () => setSpokenMode(!spokenMode));

document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
    e.preventDefault();
    conversationMode ? addTurn() : copySafeTranscript();
  }
});

if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
  setStatus("Microphone not available in this browser. The text checker still works.");
  startRecordingButton.disabled = true;
}

setSample("spoken");
