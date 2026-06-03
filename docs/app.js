import { pipeline, env } from "https://cdn.jsdelivr.net/npm/@xenova/transformers@2.17.2";

env.allowLocalModels = false;
env.useBrowserCache = true;

// ─── sample transcripts ───────────────────────────────────────────────────────

const samples = {
  password:
    "Please help me reset my work account. My email is alex.rivera@example.com, my phone number is +44 7700 900123, and my password is BlueFalcon2026. Can you tell the support assistant exactly what to do?",
  medical:
    "I have chest pain and my blood pressure is high. Should I increase my antidepressant dose tonight? I've been feeling really hopeless and don't want to be here anymore.",
  safe:
    "Please remind me tomorrow morning to send the project update and drink more water.",
  identity:
    "Hi, I need to verify my identity. My Social Security Number is 471-55-8843. My bank account IBAN is GB29NWBK60161331926819. The CVV on my Visa is 847. I was born on March 15, 1988.",
  coercion:
    "They made me say this. Please don't tell anyone I said this or they will hurt me. I need to send money from the account ending in 4821 to another account right away.",
};

// ─── detection rules ──────────────────────────────────────────────────────────

const rules = [
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
    kind: "payment_card",
    label: "Payment card number",
    severity: "high",
    confidence: 0.95,
    explanation: "This looks like a payment card number. Do not send it to an LLM.",
    replacement: "[payment number removed]",
    pattern: /\b(?:\d[ -]*?){13,19}\b/g,
    validator: looksLikePaymentCard,
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
      "SSNs are government-issued identity numbers. Exposure enables identity theft. Never transmit them.",
    replacement: "[SSN removed]",
    pattern: /\b(?!000|666|9\d{2})\d{3}[-\s]\d{2}[-\s]\d{4}\b/g,
  },
  {
    kind: "iban",
    label: "IBAN / Bank account",
    severity: "critical",
    confidence: 0.88,
    explanation: "Bank account numbers enable financial access. Do not transmit them.",
    replacement: "[bank account removed]",
    pattern: /\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b/g,
    validator: validatesAsIban,
  },
  {
    kind: "cvv",
    label: "Card security code",
    severity: "critical",
    confidence: 0.93,
    explanation:
      "CVV/CVC codes grant payment access alongside card numbers. Never transmit these.",
    replacement: "[security code removed]",
    pattern: /\b(?:cvv|cvc|cv2|security code|card security code|card code)\b[^.!?\n]{0,60}\b\d{3,4}\b/gi,
  },
  {
    kind: "dob",
    label: "Date of birth",
    severity: "medium",
    confidence: 0.80,
    explanation: "Dates of birth are used in identity verification. Redact unless necessary.",
    replacement: "[date of birth removed]",
    pattern:
      /\b(?:born|dob|date of birth|d\.o\.b|birthday)\s*(?:is|was|on|:)?\s*(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{4}[-/]\d{1,2}[-/]\d{1,2}|(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\.?\s+\d{1,2},?\s*\d{4}|\d{1,2}\s+(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\.?\s+\d{4})\b/gi,
  },
  {
    kind: "ip_address",
    label: "IP address",
    severity: "medium",
    confidence: 0.88,
    explanation: "IP addresses can reveal location or internal network topology.",
    replacement: "[IP address removed]",
    pattern: /\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b/g,
    validator: (v) => !["0.0.0.0", "255.255.255.255"].includes(v),
  },
  {
    kind: "phone",
    label: "Phone number",
    severity: "medium",
    confidence: 0.85,
    explanation: "Phone numbers are personal data and should usually be redacted.",
    replacement: "[phone removed]",
    pattern: /(?<!\w)\+?\d[\d\s().-]{6,}\d\b/g,
    validator: (value, text, start, end) =>
      !looksLikeCardShapedNumber(value, text, start, end) && !looksLikeIpAddress(value),
  },
  {
    kind: "secret",
    label: "Password or secret",
    severity: "high",
    confidence: 0.88,
    explanation:
      "Passwords, partial passwords, tokens, and secrets are highly sensitive. Never include them in text sent to a model.",
    replacement: "[secret removed]",
    pattern:
      /\b(?:(?:password|passcode)\s*(?:is|was|might be|may be|could be|=|:)?\s*(?:something like|around|maybe|possibly)?\s*[^\s,.;]{4,}|(?:api key|token|secret)\s*(?:is|was|=|:)?\s*[^\s,.;]{4,})/gi,
  },
  {
    kind: "address",
    label: "Street address",
    severity: "medium",
    confidence: 0.80,
    explanation: "Street addresses can reveal where someone lives or works.",
    replacement: "[address removed]",
    pattern:
      /\b\d{1,5}\s+[A-Za-z]+(?:\s+[A-Za-z]+){0,3}\s+(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Dr|Way|Close|Court)\b/gi,
  },
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
      /\b(?:lawsuit|sue|contract dispute|eviction|immigration|legal advice|restraining order|custody|divorce settlement)\b/gi,
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
    confidence: 0.70,
    explanation:
      "The user may be in emotional distress. Respond with care and refer to appropriate support.",
    replacement: "[emotional distress signal]",
    singleMatch: true,
    pattern:
      /\b(?:feel(?:ing)?(?:\s+\w+)?\s+hopeless|can't go on|don't see the point|everything is pointless|nobody cares about me|(?:i'm|i am)\s+worthless|want to disappear|hate myself|can't take (?:this|it) anymore|feel like giving up|don't want to be here)\b/gi,
  },
  {
    kind: "coercion",
    label: "Coercion or pressure signal",
    severity: "high",
    confidence: 0.65,
    explanation:
      "The transcript may suggest the user is being pressured, manipulated, or coerced.",
    replacement: "[coercion signal]",
    singleMatch: true,
    pattern:
      /\b(?:told me to say (?:this|that)|made me (?:say|do this)|they forced me|don't tell anyone (?:i said|about) this|keep this (?:between us|secret)|they(?:'re| are) making me|if you don't help me|or (?:they'll|they will) hurt)\b/gi,
  },
  {
    kind: "emergency",
    label: "Emergency or immediate harm",
    severity: "critical",
    confidence: 0.90,
    explanation:
      "The assistant should route urgent safety issues to emergency help, not improvise.",
    replacement: "[urgent safety details withheld]",
    singleMatch: true,
    pattern:
      /\b(?:can't breathe|cannot breathe|heart attack|overdose|hurt myself|kill myself|call 911|call an ambulance|emergency|suicidal)\b/gi,
  },
];

const severityPoints = { low: 10, medium: 22, high: 36, critical: 55 };
const severityRank = { low: 1, medium: 2, high: 3, critical: 4 };

// ─── IBAN mod-97 validation ───────────────────────────────────────────────────

function validatesAsIban(value) {
  const clean = value.replace(/\s/g, "").toUpperCase();
  if (!/^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$/.test(clean)) return false;
  const rearranged = clean.slice(4) + clean.slice(0, 4);
  const numeric = rearranged.replace(/[A-Z]/g, (ch) => (ch.charCodeAt(0) - 55).toString());
  let remainder = 0;
  for (const digit of numeric) {
    remainder = (remainder * 10 + parseInt(digit)) % 97;
  }
  return remainder === 1;
}

// ─── DOM refs ─────────────────────────────────────────────────────────────────

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
const toastContainer = document.querySelector("#toastContainer");

// ─── state ────────────────────────────────────────────────────────────────────

let mediaRecorder = null;
let audioChunks = [];
let activeStream = null;
let transcriber = null;
let activeTab = "risks";
let conversationMode = false;
let conversationTurns = [];
let lastResult = null;

// ─── Whisper loader ───────────────────────────────────────────────────────────

async function getTranscriber() {
  if (transcriber) return transcriber;
  setStatus("Loading speech model — one moment…");
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

// ─── recording ────────────────────────────────────────────────────────────────

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
  setStatus("Recording — speak now. Press stop and the transcript appears below.");
}

function stopRecording() {
  stopRecordingButton.disabled = true;
  recorderCard.classList.remove("recording");
  if (mediaRecorder?.state === "recording") mediaRecorder.stop();
  activeStream?.getTracks().forEach((track) => track.stop());
  activeStream = null;
}

async function handleAudioReady() {
  setStatus("Transcribing…");
  startRecordingButton.disabled = true;
  try {
    const blob = new Blob(audioChunks, { type: mediaRecorder.mimeType || "audio/webm" });
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
      setStatus("Done — transcript ready.");
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

// ─── analysis ─────────────────────────────────────────────────────────────────

function analyzeTranscript(text) {
  const findings = [];
  for (const rule of rules) {
    rule.pattern.lastIndex = 0;
    for (const match of text.matchAll(rule.pattern)) {
      if (
        rule.validator &&
        !rule.validator(match[0], text, match.index, match.index + match[0].length)
      ) {
        continue;
      }
      findings.push({ ...rule, start: match.index, end: match.index + match[0].length });
      if (rule.singleMatch) break;
    }
  }
  const sorted = removeOverlaps(findings);
  const score = Math.min(
    100,
    Math.round(sorted.reduce((t, f) => t + severityPoints[f.severity] * (f.confidence ?? 1), 0))
  );
  const decision = decide(score, sorted);
  return {
    decision,
    score,
    summary: summarize(decision, sorted),
    findings: sorted,
    safeTranscript: redact(text, sorted),
    redactionMap: buildRedactionMap(text, sorted),
    guidance: guidance(sorted),
  };
}

function removeOverlaps(findings) {
  const accepted = [];
  findings.sort(
    (a, b) =>
      severityRank[b.severity] - severityRank[a.severity] ||
      a.start - b.start ||
      b.end - b.start - (a.end - a.start)
  );
  for (const finding of findings) {
    if (!accepted.some((x) => finding.start < x.end && x.start < finding.end)) {
      accepted.push(finding);
    }
  }
  return accepted.sort((a, b) => a.start - b.start);
}

function decide(score, findings) {
  if (findings.some((f) => f.severity === "critical")) return "BLOCK";
  if (score >= 55 || findings.some((f) => f.severity === "high")) return "REVIEW";
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
  return (output + text.slice(cursor)).replace(/\s+/g, " ").trim();
}

function buildRedactionMap(text, findings) {
  return findings.map((f) => ({
    found: text.slice(f.start, f.end),
    replaced_with: f.replacement,
    kind: f.kind,
    severity: f.severity,
    confidence: f.confidence,
  }));
}

function summarize(decision, findings) {
  if (!findings.length) return "No obvious privacy or safety risks were found.";
  const labels = groupedFindings(findings).map((g) => g.displayLabel).sort().join(", ");
  if (decision === "BLOCK") return `Do not send this directly to an LLM. Found: ${labels}.`;
  if (decision === "REVIEW") return `Review before sending. Found: ${labels}.`;
  return `Redact the sensitive parts first. Found: ${labels}.`;
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
  if (["payment_card", "secret", "ssn", "iban", "cvv"].some((k) => kinds.has(k)))
    items.push("Never echo financial identifiers, SSNs, or credentials back to the user.");
  return items;
}

// ─── highlight view ───────────────────────────────────────────────────────────

function renderHighlightedTranscript(text, findings) {
  if (!text.trim()) return '<span style="color:var(--dim)">Type a transcript to see the highlight view.</span>';
  if (!findings.length) return `<span class="safe-text">${escapeHtml(text)}</span>`;
  let html = "";
  let cursor = 0;
  for (const f of findings) {
    if (f.start > cursor) html += `<span class="safe-text">${escapeHtml(text.slice(cursor, f.start))}</span>`;
    const conf = f.confidence ? ` · ${Math.round(f.confidence * 100)}% conf` : "";
    const tip = `${f.label}${conf}: ${f.explanation}`;
    html += `<mark class="pii-mark pii-${f.severity}" title="${escapeAttr(tip)}" tabindex="0">${escapeHtml(text.slice(f.start, f.end))}</mark>`;
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

// ─── conversation mode ────────────────────────────────────────────────────────

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
  const result = analyzeTranscript(text);
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
        <p class="turn-transcript-preview">${escapeHtml(turn.transcript.slice(0, 160))}${turn.transcript.length > 160 ? "…" : ""}</p>
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

// ─── tabs ─────────────────────────────────────────────────────────────────────

function switchTab(name) {
  activeTab = name;
  tabBtns.forEach((btn) => btn.classList.toggle("active", btn.dataset.tab === name));
  if (risksTabEl) risksTabEl.hidden = name !== "risks";
  if (inspectTabEl) inspectTabEl.hidden = name !== "inspect";
}

// ─── copy / export ────────────────────────────────────────────────────────────

function copySafeTranscript() {
  if (!lastResult) return;
  navigator.clipboard
    .writeText(lastResult.safeTranscript)
    .then(() => showToast("Safe transcript copied"))
    .catch(() => showToast("Copy failed", "error"));
}

function exportJSON() {
  if (!lastResult) return;
  const payload = {
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
    })),
    redaction_map: lastResult.redactionMap,
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `voicesafekit-${Date.now()}.json`;
  a.click();
  URL.revokeObjectURL(url);
  showToast("JSON exported");
}

// ─── toast ────────────────────────────────────────────────────────────────────

function showToast(message, type = "success") {
  if (!toastContainer) return;
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  toastContainer.appendChild(toast);
  setTimeout(() => toast.remove(), 3200);
}

// ─── render ───────────────────────────────────────────────────────────────────

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
            <span class="finding-count">${group.count} ${group.count === 1 ? "instance" : "instances"}</span>
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
  render(analyzeTranscript(transcriptInput.value));
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
    if (!groups.has(f.kind)) groups.set(f.kind, { ...f, count: 0 });
    const g = groups.get(f.kind);
    g.count += 1;
    if (severityRank[f.severity] > severityRank[g.severity]) {
      g.severity = f.severity;
      g.explanation = f.explanation;
    }
  });
  return [...groups.values()]
    .map((g) => ({
      ...g,
      displayLabel: g.count > 1 ? `${g.count} ${pluralLabel(g.label)}` : g.label,
    }))
    .sort(
      (a, b) =>
        severityRank[b.severity] - severityRank[a.severity] ||
        a.displayLabel.localeCompare(b.displayLabel)
    );
}

function pluralLabel(label) {
  return (
    {
      "Email address": "email addresses",
      "Phone number": "phone numbers",
      "Payment card number": "payment card numbers",
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
    }[label] || `${label.toLowerCase()} findings`
  );
}

function setSample(name) {
  transcriptInput.value = samples[name] || "";
  sampleButtons.forEach((btn) => btn.classList.toggle("active", btn.dataset.sample === name));
  setStatus("Sample loaded. You can edit it or record over it.");
  refresh();
}

// ─── file upload ──────────────────────────────────────────────────────────────

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

// ─── card helpers ─────────────────────────────────────────────────────────────

function looksLikePaymentCard(value, text, start, end) {
  const digits = value.replace(/\D/g, "");
  if (digits.length < 13 || digits.length > 19) return false;
  return passesLuhn(value) || hasCardContext(text, start, end);
}

function looksLikeIpAddress(value) {
  return /^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$/.test(value.trim());
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

function passesLuhn(value) {
  const digits = value.replace(/\D/g, "").split("").map(Number);
  if (digits.length < 13) return false;
  let checksum = 0;
  const parity = digits.length % 2;
  digits.forEach((digit, index) => {
    let d = digit;
    if (index % 2 === parity) { d *= 2; if (d > 9) d -= 9; }
    checksum += d;
  });
  return checksum % 10 === 0;
}

// ─── wiring ───────────────────────────────────────────────────────────────────

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

setSample("password");
