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
    explanation: "This looks like a payment card number — 13 to 19 digits in a row. Do not send it to an LLM.",
    replacement: "[payment number removed]",
    // Matches 13–19 digits optionally separated by spaces or dashes (card format).
    // No Luhn gate — a safety tool should flag anything that *looks* like a card,
    // not silently ignore it because the digits fail a checksum.
    pattern: /\b(?:\d[ -]*){12,18}\d\b/g,
    validator: looksLikeCardFormat
  },
  {
    kind: "phone",
    label: "Phone number",
    severity: "medium",
    explanation: "Phone numbers are personal data and should usually be redacted.",
    replacement: "[phone removed]",
    pattern: /(?<!\w)\+?\d[\d\s().-]{6,}\d\b/g,
    // Reject strings whose stripped digit count is 13 or more — those are card-length,
    // not phone-length. The card rule above (higher severity) handles that range.
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
    pattern:
      /\b(?:chest pain|diagnose|dose|medication|symptoms|blood pressure|antibiotic|panic attack)\b/gi
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
    pattern:
      /\b(?:can't breathe|cannot breathe|heart attack|overdose|hurt myself|kill myself|emergency)\b/gi
  }
];

const severityPoints = { low: 10, medium: 22, high: 36, critical: 55 };
const severityRank = { low: 1, medium: 2, high: 3, critical: 4 };
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

const transcriptInput = document.querySelector("#transcriptInput");
const analyzeButton = document.querySelector("#analyzeButton");
const startRecordingButton = document.querySelector("#startRecording");
const stopRecordingButton = document.querySelector("#stopRecording");
const clearButton = document.querySelector("#clearButton");
const fileInput = document.querySelector("#fileInput");
const recordingStatus = document.querySelector("#recordingStatus");
const recorderCard = document.querySelector(".recorder-card");
const audioPreview = document.querySelector("#audioPreview");
const decisionEl = document.querySelector("#decision");
const scoreEl = document.querySelector("#score");
const summaryEl = document.querySelector("#summary");
const findingsEl = document.querySelector("#findings");
const safeTranscriptEl = document.querySelector("#safeTranscript");
const guidanceEl = document.querySelector("#guidance");
const heroDecision = document.querySelector("#heroDecision");
const heroSummary = document.querySelector("#heroSummary");
const sampleButtons = [...document.querySelectorAll("[data-sample]")];

let mediaRecorder = null;
let audioChunks = [];
let activeStream = null;
let recognition = null;
let isRecordingActive = false;
let recordingBaseText = "";
let speechText = "";

// ─── analysis ───────────────────────────────────────────────────────────────

function analyzeTranscript(text) {
  const findings = [];
  for (const rule of rules) {
    rule.pattern.lastIndex = 0;
    for (const match of text.matchAll(rule.pattern)) {
      if (rule.validator && !rule.validator(match[0])) continue;
      findings.push({
        ...rule,
        start: match.index,
        end: match.index + match[0].length
      });
      if (rule.singleMatch) break;
    }
  }

  const sorted = removeOverlaps(findings);
  const score = Math.min(
    100,
    sorted.reduce((total, f) => total + severityPoints[f.severity], 0)
  );
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
  const prioritySorted = findings.sort(
    (a, b) =>
      severityRank[b.severity] - severityRank[a.severity] ||
      a.start - b.start ||
      b.end - b.start - (a.end - a.start)
  );
  for (const f of prioritySorted) {
    const overlaps = accepted.some((item) => f.start < item.end && item.start < f.end);
    if (!overlaps) accepted.push(f);
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
  let cursor = 0;
  let output = "";
  for (const f of findings) {
    output += text.slice(cursor, f.start);
    output += f.replacement;
    cursor = f.end;
  }
  output += text.slice(cursor);
  return output.replace(/\s+/g, " ").trim();
}

function summarize(decision, findings) {
  if (!findings.length) return "No obvious privacy or safety risks were found.";
  const labels = [...new Set(findings.map((f) => f.label))].sort().join(", ");
  if (decision === "BLOCK") return `Do not send this directly to an LLM. Found: ${labels}.`;
  if (decision === "REVIEW") return `Review before sending. Found: ${labels}.`;
  return `Redact the sensitive parts first. Found: ${labels}.`;
}

function guidance(findings) {
  if (!findings.length) {
    return ["Proceed normally, but keep the user's data local whenever possible."];
  }
  const kinds = new Set(findings.map((f) => f.kind));
  const items = [
    "Remove or mask private details before sending the transcript to an LLM.",
    "Explain the limitation to the user in plain language."
  ];
  if (kinds.has("emergency")) {
    items.unshift("For urgent safety issues, guide the user to emergency help immediately.");
  }
  if (["medical", "legal", "financial"].some((k) => kinds.has(k))) {
    items.push("Give general information only and suggest a qualified professional.");
  }
  if (["payment_card", "secret"].some((k) => kinds.has(k))) {
    items.push("Never echo passwords, tokens, or payment details back to the user.");
  }
  return items;
}

// ─── validators ─────────────────────────────────────────────────────────────

// Returns true for anything that looks structurally like a payment card:
// 13–19 digits optionally separated by spaces or dashes.
// We deliberately do NOT gate on the Luhn checksum — a safety tool should
// flag anything that *looks* like a card, not silently miss it because the
// user typed a digit wrong.
function looksLikeCardFormat(value) {
  const digits = value.replace(/\D/g, "");
  return digits.length >= 13 && digits.length <= 19;
}

// ─── rendering ──────────────────────────────────────────────────────────────

function render(result) {
  decisionEl.textContent = result.decision;
  heroDecision.textContent = result.decision;
  scoreEl.textContent = `${result.score}/100`;
  summaryEl.textContent = result.summary;
  heroSummary.textContent = result.summary;
  safeTranscriptEl.textContent = result.safeTranscript || "No transcript yet.";

  findingsEl.innerHTML = result.findings.length
    ? result.findings
        .map(
          (f) => `
            <article class="finding ${f.severity}">
              <strong>${f.label} / ${f.severity}</strong>
              <p>${f.explanation}</p>
            </article>
          `
        )
        .join("")
    : `<article class="finding"><strong>No findings</strong><p>This transcript looks safe for a normal assistant response.</p></article>`;

  guidanceEl.innerHTML = result.guidance.map((item) => `<p>${item}</p>`).join("");
}

function refresh() {
  render(analyzeTranscript(transcriptInput.value));
}

function setSample(name) {
  transcriptInput.value = samples[name];
  sampleButtons.forEach((btn) => btn.classList.toggle("active", btn.dataset.sample === name));
  recordingStatus.textContent = "Sample loaded. You can edit it or record over it.";
  refresh();
}

// ─── recording ──────────────────────────────────────────────────────────────

async function startRecording() {
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    recordingStatus.textContent =
      "This browser cannot record audio here. Try Chrome or Edge on the HTTPS GitHub Pages link.";
    startRecordingButton.disabled = true;
    return;
  }

  try {
    activeStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioChunks = [];
    isRecordingActive = true;
    mediaRecorder = new MediaRecorder(activeStream);
    recordingBaseText = transcriptInput.value.trim();
    speechText = "";

    mediaRecorder.addEventListener("dataavailable", (event) => {
      if (event.data.size > 0) audioChunks.push(event.data);
    });

    mediaRecorder.addEventListener("stop", () => {
      const audioBlob = new Blob(audioChunks, { type: mediaRecorder.mimeType || "audio/webm" });
      audioPreview.src = URL.createObjectURL(audioBlob);
      audioPreview.hidden = false;
      activeStream?.getTracks().forEach((t) => t.stop());
      activeStream = null;
      recorderCard.classList.remove("recording");
      startRecordingButton.disabled = false;
      stopRecordingButton.disabled = true;
      mediaRecorder = null;
      recordingStatus.textContent =
        speechText.trim().length > 0
          ? "Done. Transcript updated from your recording."
          : "Recording saved. If no words appeared, your browser may not support live speech-to-text — paste the transcript manually.";
      refresh();
    });

    mediaRecorder.start();
    startSpeechRecognition();
    recorderCard.classList.add("recording");
    startRecordingButton.disabled = true;
    stopRecordingButton.disabled = false;
    recordingStatus.textContent = SpeechRecognition
      ? "Listening — speak now. Words will appear automatically."
      : "Recording audio. Live speech-to-text is not available in this browser.";
  } catch (error) {
    isRecordingActive = false;
    recordingStatus.textContent = `Microphone access failed: ${error.message}`;
    activeStream?.getTracks().forEach((t) => t.stop());
    activeStream = null;
    if (mediaRecorder?.state === "recording") mediaRecorder.stop();
    recorderCard.classList.remove("recording");
    startRecordingButton.disabled = false;
    stopRecordingButton.disabled = true;
  }
}

function stopRecording() {
  isRecordingActive = false;
  stopSpeechRecognition();
  if (mediaRecorder?.state === "recording") {
    mediaRecorder.stop();
  }
}

function stopSpeechRecognition() {
  if (recognition) {
    recognition.onend = null;
    try { recognition.stop(); } catch (_) {}
    recognition = null;
  }
}

function startSpeechRecognition() {
  if (!SpeechRecognition) return;

  function createAndStart() {
    if (!isRecordingActive) return;

    try {
      recognition = new SpeechRecognition();
      recognition.lang = "en-GB";
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.maxAlternatives = 1;

      recognition.onresult = (event) => {
        let interim = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const t = event.results[i][0].transcript;
          if (event.results[i].isFinal) {
            speechText += `${t} `;
          } else {
            interim += t;
          }
        }
        transcriptInput.value = [recordingBaseText, speechText, interim]
          .filter((p) => p.trim().length > 0)
          .join(" ")
          .trim();
        recordingStatus.textContent = interim
          ? `Hearing: "${interim}"`
          : "Recording. Transcript is updating.";
        refresh();
      };

      recognition.onerror = (event) => {
        // "no-speech" and "aborted" are normal — don't show them as errors
        if (event.error !== "no-speech" && event.error !== "aborted") {
          recordingStatus.textContent = `Speech recognition: ${event.error}. Audio still recording.`;
        }
      };

      // The browser stops SpeechRecognition after a period of silence.
      // Restart it automatically so the user never has to press anything again.
      recognition.onend = () => {
        if (isRecordingActive) {
          setTimeout(createAndStart, 150);
        }
      };

      recognition.start();
    } catch (error) {
      recognition = null;
      recordingStatus.textContent =
        "Recording audio. Live speech-to-text could not start in this browser.";
    }
  }

  createAndStart();
}

// ─── file upload ─────────────────────────────────────────────────────────────

async function handleFileUpload(event) {
  const file = event.target.files?.[0];
  if (!file) return;

  const isText = file.type.startsWith("text/") || /\.(txt|md|json)$/i.test(file.name);
  const isAudio = file.type.startsWith("audio/");

  if (isText) {
    transcriptInput.value = await file.text();
    recordingStatus.textContent = `Loaded: ${file.name}`;
    refresh();
    return;
  }

  if (isAudio) {
    audioPreview.src = URL.createObjectURL(file);
    audioPreview.hidden = false;
    recordingStatus.textContent =
      `Audio loaded: ${file.name}. Paste or type the transcript below to check it.`;
    return;
  }

  recordingStatus.textContent = "Unsupported file. Upload a .txt transcript or an audio file.";
}

function clearAll() {
  transcriptInput.value = "";
  fileInput.value = "";
  audioPreview.removeAttribute("src");
  audioPreview.hidden = true;
  recordingStatus.textContent = "Cleared. Record, upload, or type a new transcript.";
  sampleButtons.forEach((btn) => btn.classList.remove("active"));
  refresh();
}

// ─── wiring ──────────────────────────────────────────────────────────────────

startRecordingButton.addEventListener("click", startRecording);
stopRecordingButton.addEventListener("click", stopRecording);
clearButton.addEventListener("click", clearAll);
fileInput.addEventListener("change", handleFileUpload);
analyzeButton.addEventListener("click", refresh);
transcriptInput.addEventListener("input", refresh);
sampleButtons.forEach((btn) =>
  btn.addEventListener("click", () => setSample(btn.dataset.sample))
);

if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
  recordingStatus.textContent =
    "Audio recording is unavailable in this browser. The transcript checker still works.";
  startRecordingButton.disabled = true;
}

setSample("password");
