import { pipeline, env } from "https://cdn.jsdelivr.net/npm/@xenova/transformers@2.17.2";

// Use browser cache so the model only downloads once.
env.allowLocalModels = false;
env.useBrowserCache = true;

// ─── detection rules ─────────────────────────────────────────────────────────

const samples = {
  password:
    "Please help me reset my work account. My email is alex.rivera@example.com, my phone number is +44 7700 900123, and my password is BlueFalcon2026. Can you tell the support assistant exactly what to do?",
  medical:
    "I have chest pain and my blood pressure is high. Should I increase my medication dose tonight?",
  safe:
    "Please remind me tomorrow morning to send the project update and drink more water."
};

const rules = [
  {
    kind: "email",
    label: "Email address",
    severity: "medium",
    explanation: "Email addresses can identify a person. Remove them before sending text to a model.",
    replacement: "[email removed]",
    pattern: /\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b/g
  },
  {
    kind: "payment_card",
    label: "Payment card number",
    severity: "high",
    explanation: "This looks like a payment card number. Do not send it to an LLM.",
    replacement: "[payment number removed]",
    pattern: /\b(?:\d[ -]*?){13,19}\b/g,
    validator: looksLikePaymentCard
  },
  {
    kind: "phone",
    label: "Phone number",
    severity: "medium",
    explanation: "Phone numbers are personal data and should usually be redacted.",
    replacement: "[phone removed]",
    pattern: /(?<!\w)\+?\d[\d\s().-]{6,}\d\b/g,
    validator: (value, text, start, end) => !looksLikeCardShapedNumber(value, text, start, end)
  },
  {
    kind: "secret",
    label: "Password or secret",
    severity: "high",
    explanation:
      "Passwords, partial passwords, tokens, and secrets are highly sensitive. Never include them in text sent to a model.",
    replacement: "[secret removed]",
    pattern:
      /\b(?:(?:password|passcode)\s*(?:is|was|might be|may be|could be|=|:)?\s*(?:something like|around|maybe|possibly)?\s*[^\s,.;]{4,}|(?:api key|token|secret)\s*(?:is|was|=|:)?\s*[^\s,.;]{4,})/gi
  },
  {
    kind: "address",
    label: "Street address",
    severity: "medium",
    explanation: "Street addresses can reveal where someone lives or works.",
    replacement: "[address removed]",
    pattern:
      /\b\d{1,5}\s+[A-Za-z]+(?:\s+[A-Za-z]+){0,3}\s+(?:Street|St|Road|Rd|Avenue|Ave|Lane|Ln|Drive|Dr|Way|Close|Court)\b/gi
  },
  {
    kind: "medical",
    label: "Medical advice request",
    severity: "high",
    explanation: "Medical questions should be handled carefully and should not replace a clinician.",
    replacement: "[medical details withheld]",
    singleMatch: true,
    pattern: /\b(?:chest pain|diagnose|dose|medication|symptoms|blood pressure|antibiotic|panic attack)\b/gi
  },
  {
    kind: "legal",
    label: "Legal advice request",
    severity: "high",
    explanation: "Legal questions need careful boundaries and may require a professional.",
    replacement: "[legal details withheld]",
    singleMatch: true,
    pattern: /\b(?:lawsuit|sue|contract dispute|eviction|immigration|legal advice)\b/gi
  },
  {
    kind: "financial",
    label: "Financial advice request",
    severity: "high",
    explanation: "Financial advice can affect someone's money and should be handled with caution.",
    replacement: "[financial details withheld]",
    singleMatch: true,
    pattern: /\b(?:invest all|stock tip|crypto|loan application|credit score|mortgage)\b/gi
  },
  {
    kind: "emergency",
    label: "Emergency or immediate harm",
    severity: "critical",
    explanation: "The assistant should route urgent safety issues to emergency help, not improvise.",
    replacement: "[urgent safety details withheld]",
    singleMatch: true,
    pattern: /\b(?:can't breathe|cannot breathe|heart attack|overdose|hurt myself|kill myself|emergency)\b/gi
  }
];

const severityPoints = { low: 10, medium: 22, high: 36, critical: 55 };
const severityRank = { low: 1, medium: 2, high: 3, critical: 4 };

// ─── DOM refs ────────────────────────────────────────────────────────────────

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
const safeTranscriptEl = document.querySelector("#safeTranscript");
const guidanceEl = document.querySelector("#guidance");
const heroDecision = document.querySelector("#heroDecision");
const heroSummary = document.querySelector("#heroSummary");
const sampleButtons = [...document.querySelectorAll("[data-sample]")];

// ─── state ───────────────────────────────────────────────────────────────────

let mediaRecorder = null;
let audioChunks = [];
let activeStream = null;
let transcriber = null;

// ─── Whisper loader ──────────────────────────────────────────────────────────

async function getTranscriber() {
  if (transcriber) return transcriber;
  setStatus("Loading speech model — one moment...");
  transcriber = await pipeline("automatic-speech-recognition", "Xenova/whisper-tiny.en", {
    progress_callback: (progress) => {
      if (progress.status === "downloading") {
        const pct = progress.total ? Math.round((progress.loaded / progress.total) * 100) : "?";
        setStatus(`Loading speech model: ${pct}%`);
      }
    }
  });
  return transcriber;
}

// ─── recording ───────────────────────────────────────────────────────────────

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

  // Preload the model while the user is speaking so the stop step feels faster.
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
  setStatus("Transcribing...");
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

// ─── analysis ────────────────────────────────────────────────────────────────

function analyzeTranscript(text) {
  const findings = [];
  for (const rule of rules) {
    rule.pattern.lastIndex = 0;
    for (const match of text.matchAll(rule.pattern)) {
      if (rule.validator && !rule.validator(match[0], text, match.index, match.index + match[0].length)) {
        continue;
      }
      findings.push({ ...rule, start: match.index, end: match.index + match[0].length });
      if (rule.singleMatch) break;
    }
  }
  const sorted = removeOverlaps(findings);
  const score = Math.min(100, sorted.reduce((total, finding) => total + severityPoints[finding.severity], 0));
  const decision = decide(score, sorted);
  return {
    decision,
    score,
    summary: summarize(decision, sorted),
    findings: sorted,
    safeTranscript: redact(text, sorted),
    guidance: guidance(sorted)
  };
}

function removeOverlaps(findings) {
  const accepted = [];
  findings.sort((a, b) =>
    severityRank[b.severity] - severityRank[a.severity] ||
    a.start - b.start ||
    b.end - b.start - (a.end - a.start)
  );
  for (const finding of findings) {
    if (!accepted.some((item) => finding.start < item.end && item.start < finding.end)) {
      accepted.push(finding);
    }
  }
  return accepted.sort((a, b) => a.start - b.start);
}

function decide(score, findings) {
  if (findings.some((finding) => finding.severity === "critical")) return "BLOCK";
  if (score >= 55 || findings.some((finding) => finding.severity === "high")) return "REVIEW";
  if (score >= 22) return "REDACT";
  return "SAFE";
}

function redact(text, findings) {
  if (!findings.length) return text.trim();
  let output = "";
  let cursor = 0;
  for (const finding of findings) {
    output += text.slice(cursor, finding.start) + finding.replacement;
    cursor = finding.end;
  }
  return (output + text.slice(cursor)).replace(/\s+/g, " ").trim();
}

function summarize(decision, findings) {
  if (!findings.length) return "No obvious privacy or safety risks were found.";
  const labels = groupedFindings(findings)
    .map((group) => group.displayLabel)
    .sort()
    .join(", ");
  if (decision === "BLOCK") return `Do not send this directly to an LLM. Found: ${labels}.`;
  if (decision === "REVIEW") return `Review before sending. Found: ${labels}.`;
  return `Redact the sensitive parts first. Found: ${labels}.`;
}

function guidance(findings) {
  if (!findings.length) {
    return ["Proceed normally, but keep the user's data local whenever possible."];
  }
  const kinds = new Set(findings.map((finding) => finding.kind));
  const items = [
    "Remove or mask private details before sending the transcript to an LLM.",
    "Explain the limitation to the user in plain language."
  ];
  if (kinds.has("emergency")) {
    items.unshift("For urgent safety issues, guide the user to emergency help immediately.");
  }
  if (["medical", "legal", "financial"].some((kind) => kinds.has(kind))) {
    items.push("Give general information only and suggest a qualified professional.");
  }
  if (["payment_card", "secret"].some((kind) => kinds.has(kind))) {
    items.push("Never echo passwords, tokens, or payment details back to the user.");
  }
  return items;
}

// ─── render ──────────────────────────────────────────────────────────────────

function render(result) {
  decisionEl.textContent = result.decision;
  heroDecision.textContent = result.decision;
  scoreEl.textContent = `${result.score}/100`;
  summaryEl.textContent = result.summary;
  heroSummary.textContent = result.summary;
  safeTranscriptEl.textContent = result.safeTranscript || "No transcript yet.";
  const groups = groupedFindings(result.findings);
  findingsEl.innerHTML = groups.length
    ? groups
        .map(
          (group) => `
            <article class="finding ${group.severity}">
              <strong>${group.displayLabel} / ${group.severity}</strong>
              <p>${group.explanation}</p>
            </article>
          `
        )
        .join("")
    : `<article class="finding"><strong>No findings</strong><p>This transcript looks safe.</p></article>`;
  guidanceEl.innerHTML = result.guidance.map((item) => `<p>${item}</p>`).join("");
}

function refresh() {
  render(analyzeTranscript(transcriptInput.value));
}

function setStatus(message) {
  recordingStatus.textContent = message;
}

function groupedFindings(findings) {
  const groups = new Map();
  findings.forEach((finding) => {
    if (!groups.has(finding.kind)) {
      groups.set(finding.kind, { ...finding, count: 0 });
    }
    const group = groups.get(finding.kind);
    group.count += 1;
    if (severityRank[finding.severity] > severityRank[group.severity]) {
      group.severity = finding.severity;
      group.explanation = finding.explanation;
    }
  });
  return [...groups.values()]
    .map((group) => ({
      ...group,
      displayLabel: group.count > 1 ? `${group.count} ${pluralLabel(group.label)}` : group.label
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
      "Password or secret": "password or secret mentions",
      "Street address": "street addresses",
      "Medical advice request": "medical advice requests",
      "Legal advice request": "legal advice requests",
      "Financial advice request": "financial advice requests",
      "Emergency or immediate harm": "emergency or immediate harm phrases"
    }[label] || `${label.toLowerCase()} findings`
  );
}

function setSample(name) {
  transcriptInput.value = samples[name];
  sampleButtons.forEach((button) => button.classList.toggle("active", button.dataset.sample === name));
  setStatus("Sample loaded. You can edit it or record over it.");
  refresh();
}

// ─── file upload ─────────────────────────────────────────────────────────────

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
  setStatus("Cleared. Record, upload, or type a new transcript.");
  sampleButtons.forEach((button) => button.classList.remove("active"));
  refresh();
}

function looksLikePaymentCard(value, text, start, end) {
  const digits = value.replace(/\D/g, "");
  if (digits.length < 13 || digits.length > 19) return false;
  return passesLuhn(value) || hasCardContext(text, start, end);
}

function looksLikeCardShapedNumber(value, text, start, end) {
  const digits = value.replace(/\D/g, "");
  if (digits.length < 13 || value.trim().startsWith("+")) return false;
  return digits.length <= 19 || hasCardContext(text, start, end);
}

function hasCardContext(text, start, end) {
  const windowText = text.slice(Math.max(0, start - 32), Math.min(text.length, end + 32)).toLowerCase();
  return ["card", "credit", "debit", "visa", "mastercard", "payment"].some((phrase) =>
    windowText.includes(phrase)
  );
}

function passesLuhn(value) {
  const digits = value.replace(/\D/g, "").split("").map(Number);
  if (digits.length < 13) return false;
  let checksum = 0;
  const parity = digits.length % 2;
  digits.forEach((digit, index) => {
    let checkedDigit = digit;
    if (index % 2 === parity) {
      checkedDigit *= 2;
      if (checkedDigit > 9) checkedDigit -= 9;
    }
    checksum += checkedDigit;
  });
  return checksum % 10 === 0;
}

// ─── wiring ──────────────────────────────────────────────────────────────────

startRecordingButton.addEventListener("click", startRecording);
stopRecordingButton.addEventListener("click", stopRecording);
clearButton.addEventListener("click", clearAll);
fileInput.addEventListener("change", handleFileUpload);
transcriptInput.addEventListener("input", refresh);
sampleButtons.forEach((button) => button.addEventListener("click", () => setSample(button.dataset.sample)));

if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
  setStatus("Microphone not available in this browser. The text checker still works.");
  startRecordingButton.disabled = true;
}

setSample("password");
