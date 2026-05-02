import { pipeline, env } from "https://cdn.jsdelivr.net/npm/@xenova/transformers@2.17.2";

// Use browser cache so the model only downloads once (~75 MB).
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
    pattern: /\b(?:\d[ -]*){12,18}\d\b/g,
    validator: (val) => { const d = val.replace(/\D/g, ""); return d.length >= 13 && d.length <= 19; }
  },
  {
    kind: "phone",
    label: "Phone number",
    severity: "medium",
    explanation: "Phone numbers are personal data and should usually be redacted.",
    replacement: "[phone removed]",
    pattern: /(?<!\w)\+?\d[\d\s().-]{6,}\d\b/g,
    validator: (val) => val.replace(/\D/g, "").length < 13
  },
  {
    kind: "secret",
    label: "Password or secret",
    severity: "high",
    explanation: "The transcript appears to contain a password, token, or secret.",
    replacement: "[secret removed]",
    pattern: /\b(?:password|passcode|api key|token|secret)\s*(?:is|=|:)?\s*[^\s,.;]{4,}/gi
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
const severityRank   = { low: 1,  medium: 2,  high: 3,  critical: 4  };

// ─── DOM refs ────────────────────────────────────────────────────────────────

const transcriptInput     = document.querySelector("#transcriptInput");
const analyzeButton       = document.querySelector("#analyzeButton");
const startRecordingButton = document.querySelector("#startRecording");
const stopRecordingButton  = document.querySelector("#stopRecording");
const clearButton         = document.querySelector("#clearButton");
const fileInput           = document.querySelector("#fileInput");
const recordingStatus     = document.querySelector("#recordingStatus");
const recorderCard        = document.querySelector(".recorder-card");
const decisionEl          = document.querySelector("#decision");
const scoreEl             = document.querySelector("#score");
const summaryEl           = document.querySelector("#summary");
const findingsEl          = document.querySelector("#findings");
const safeTranscriptEl    = document.querySelector("#safeTranscript");
const guidanceEl          = document.querySelector("#guidance");
const heroDecision        = document.querySelector("#heroDecision");
const heroSummary         = document.querySelector("#heroSummary");
const sampleButtons       = [...document.querySelectorAll("[data-sample]")];

// ─── state ───────────────────────────────────────────────────────────────────

let mediaRecorder  = null;
let audioChunks    = [];
let activeStream   = null;
let transcriber    = null;

// ─── Whisper loader ──────────────────────────────────────────────────────────

async function getTranscriber() {
  if (transcriber) return transcriber;
  setStatus("Loading speech model — one moment…");
  transcriber = await pipeline(
    "automatic-speech-recognition",
    "Xenova/whisper-tiny.en",
    { progress_callback: (p) => {
        if (p.status === "downloading") {
          const pct = p.total ? Math.round((p.loaded / p.total) * 100) : "?";
          setStatus(`Loading speech model: ${pct}%`);
        }
      }
    }
  );
  return transcriber;
}

// ─── recording ───────────────────────────────────────────────────────────────

async function startRecording() {
  startRecordingButton.disabled = true;

  try {
    activeStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    setStatus(`Microphone access denied: ${err.message}`);
    startRecordingButton.disabled = false;
    return;
  }

  // Preload the model while the user is speaking (hides the wait time).
  getTranscriber().catch(() => {});

  audioChunks = [];
  mediaRecorder = new MediaRecorder(activeStream);

  mediaRecorder.addEventListener("dataavailable", (e) => {
    if (e.data.size > 0) audioChunks.push(e.data);
  });

  mediaRecorder.addEventListener("stop", handleAudioReady);

  mediaRecorder.start();
  recorderCard.classList.add("recording");
  stopRecordingButton.disabled = false;
  setStatus("Recording — speak now. Press stop when done.");
}

function stopRecording() {
  stopRecordingButton.disabled = true;
  recorderCard.classList.remove("recording");
  if (mediaRecorder?.state === "recording") mediaRecorder.stop();
  activeStream?.getTracks().forEach((t) => t.stop());
  activeStream = null;
}

async function handleAudioReady() {
  setStatus("Transcribing…");
  startRecordingButton.disabled = true;

  try {
    const blob = new Blob(audioChunks, { type: mediaRecorder.mimeType || "audio/webm" });
    const arrayBuffer = await blob.arrayBuffer();

    // Decode to 16 kHz mono — the sample rate Whisper expects.
    const audioCtx = new AudioContext({ sampleRate: 16000 });
    const decoded  = await audioCtx.decodeAudioData(arrayBuffer);
    await audioCtx.close();
    const float32  = decoded.getChannelData(0);

    const model  = await getTranscriber();
    const result = await model(float32, { sampling_rate: 16000 });
    const text   = (result.text || "").trim();

    if (text) {
      const existing = transcriptInput.value.trim();
      transcriptInput.value = existing ? `${existing} ${text}` : text;
      setStatus("Done — transcript ready.");
    } else {
      setStatus("Nothing was picked up. Try speaking more clearly or check your mic.");
    }
  } catch (err) {
    setStatus(`Transcription failed: ${err.message}`);
    console.error(err);
  } finally {
    startRecordingButton.disabled = false;
    mediaRecorder = null;
    audioChunks   = [];
    refresh();
  }
}

// ─── analysis ────────────────────────────────────────────────────────────────

function analyzeTranscript(text) {
  const findings = [];
  for (const rule of rules) {
    rule.pattern.lastIndex = 0;
    for (const match of text.matchAll(rule.pattern)) {
      if (rule.validator && !rule.validator(match[0])) continue;
      findings.push({ ...rule, start: match.index, end: match.index + match[0].length });
      if (rule.singleMatch) break;
    }
  }
  const sorted = removeOverlaps(findings);
  const score  = Math.min(100, sorted.reduce((n, f) => n + severityPoints[f.severity], 0));
  const decision = decide(score, sorted);
  return { decision, score, summary: summarize(decision, sorted), findings: sorted,
           safeTranscript: redact(text, sorted), guidance: guidance(sorted) };
}

function removeOverlaps(findings) {
  const accepted = [];
  findings.sort((a, b) =>
    severityRank[b.severity] - severityRank[a.severity] || a.start - b.start
  );
  for (const f of findings) {
    if (!accepted.some((x) => f.start < x.end && x.start < f.end)) accepted.push(f);
  }
  return accepted.sort((a, b) => a.start - b.start);
}

function decide(score, findings) {
  if (findings.some((f) => f.severity === "critical")) return "BLOCK";
  if (score >= 55 || findings.some((f) => f.severity === "high")) return "REVIEW";
  if (score >= 22) return "REDACT";
  return "SAFE";
}

function redact(text, findings) {
  if (!findings.length) return text.trim();
  let out = "", cursor = 0;
  for (const f of findings) { out += text.slice(cursor, f.start) + f.replacement; cursor = f.end; }
  return (out + text.slice(cursor)).replace(/\s+/g, " ").trim();
}

function summarize(decision, findings) {
  if (!findings.length) return "No obvious privacy or safety risks were found.";
  const labels = [...new Set(findings.map((f) => f.label))].sort().join(", ");
  if (decision === "BLOCK")  return `Do not send this directly to an LLM. Found: ${labels}.`;
  if (decision === "REVIEW") return `Review before sending. Found: ${labels}.`;
  return `Redact the sensitive parts first. Found: ${labels}.`;
}

function guidance(findings) {
  if (!findings.length) return ["Proceed normally, but keep the user's data local whenever possible."];
  const kinds = new Set(findings.map((f) => f.kind));
  const items = [
    "Remove or mask private details before sending the transcript to an LLM.",
    "Explain the limitation to the user in plain language."
  ];
  if (kinds.has("emergency")) items.unshift("For urgent safety issues, guide the user to emergency help immediately.");
  if (["medical","legal","financial"].some((k) => kinds.has(k))) items.push("Give general information only and suggest a qualified professional.");
  if (["payment_card","secret"].some((k) => kinds.has(k))) items.push("Never echo passwords, tokens, or payment details back to the user.");
  return items;
}

// ─── render ──────────────────────────────────────────────────────────────────

function render(result) {
  decisionEl.textContent  = result.decision;
  heroDecision.textContent = result.decision;
  scoreEl.textContent     = `${result.score}/100`;
  summaryEl.textContent   = result.summary;
  heroSummary.textContent  = result.summary;
  safeTranscriptEl.textContent = result.safeTranscript || "No transcript yet.";
  findingsEl.innerHTML = result.findings.length
    ? result.findings.map((f) => `
        <article class="finding ${f.severity}">
          <strong>${f.label} / ${f.severity}</strong>
          <p>${f.explanation}</p>
        </article>`).join("")
    : `<article class="finding"><strong>No findings</strong><p>This transcript looks safe.</p></article>`;
  guidanceEl.innerHTML = result.guidance.map((g) => `<p>${g}</p>`).join("");
}

function refresh() { render(analyzeTranscript(transcriptInput.value)); }

function setStatus(msg) { recordingStatus.textContent = msg; }

function setSample(name) {
  transcriptInput.value = samples[name];
  sampleButtons.forEach((b) => b.classList.toggle("active", b.dataset.sample === name));
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
  sampleButtons.forEach((b) => b.classList.remove("active"));
  refresh();
}

// ─── wiring ──────────────────────────────────────────────────────────────────

startRecordingButton.addEventListener("click", startRecording);
stopRecordingButton.addEventListener("click", stopRecording);
clearButton.addEventListener("click", clearAll);
fileInput.addEventListener("change", handleFileUpload);
analyzeButton.addEventListener("click", refresh);
transcriptInput.addEventListener("input", refresh);
sampleButtons.forEach((b) => b.addEventListener("click", () => setSample(b.dataset.sample)));

if (!navigator.mediaDevices?.getUserMedia) {
  setStatus("Microphone not available in this browser. The text checker still works.");
  startRecordingButton.disabled = true;
}

setSample("password");
