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
    kind: "phone",
    label: "Phone number",
    severity: "medium",
    explanation: "Phone numbers are personal data and should usually be redacted.",
    replacement: "[phone removed]",
    pattern: /(?<!\w)\+?\d[\d\s().-]{7,}\d\b/g
  },
  {
    kind: "payment_card",
    label: "Payment card-like number",
    severity: "high",
    explanation: "This looks like a payment card number. Do not send it to an LLM.",
    replacement: "[payment number removed]",
    pattern: /\b(?:\d[ -]*?){13,19}\b/g,
    validator: looksLikeCard
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
let recordingBaseText = "";
let speechText = "";

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
    sorted.reduce((total, finding) => total + severityPoints[finding.severity], 0)
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
  for (const finding of prioritySorted) {
    const overlaps = accepted.some((item) => finding.start < item.end && item.start < finding.end);
    if (!overlaps) accepted.push(finding);
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
  let cursor = 0;
  let output = "";
  for (const finding of findings) {
    output += text.slice(cursor, finding.start);
    output += finding.replacement;
    cursor = finding.end;
  }
  output += text.slice(cursor);
  return output.replace(/\s+/g, " ").trim();
}

function summarize(decision, findings) {
  if (!findings.length) return "No obvious privacy or safety risks were found.";
  const labels = [...new Set(findings.map((finding) => finding.label))].sort().join(", ");
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
          (finding) => `
            <article class="finding ${finding.severity}">
              <strong>${finding.label} / ${finding.severity}</strong>
              <p>${finding.explanation}</p>
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
  sampleButtons.forEach((button) => button.classList.toggle("active", button.dataset.sample === name));
  recordingStatus.textContent = "Sample loaded. You can edit it or record over it.";
  refresh();
}

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
    mediaRecorder = new MediaRecorder(activeStream);
    recordingBaseText = transcriptInput.value.trim();
    speechText = "";

    mediaRecorder.addEventListener("dataavailable", (event) => {
      if (event.data.size > 0) audioChunks.push(event.data);
    });

    mediaRecorder.addEventListener("stop", (event) => {
      const audioBlob = new Blob(audioChunks, { type: event.target?.mimeType || "audio/webm" });
      audioPreview.src = URL.createObjectURL(audioBlob);
      audioPreview.hidden = false;
      activeStream?.getTracks().forEach((track) => track.stop());
      activeStream = null;
      recorderCard.classList.remove("recording");
      startRecordingButton.disabled = false;
      stopRecordingButton.disabled = true;
      mediaRecorder = null;
      recordingStatus.textContent =
        speechText.trim().length > 0
          ? "Recording saved and transcript updated."
          : "Recording saved. If no transcript appeared, type or paste the words below.";
      refresh();
    });

    mediaRecorder.start();
    startSpeechRecognition();
    recorderCard.classList.add("recording");
    startRecordingButton.disabled = true;
    stopRecordingButton.disabled = false;
    recordingStatus.textContent = SpeechRecognition
      ? "Recording. Speak clearly; live transcript will appear below."
      : "Recording audio. This browser does not expose live speech-to-text.";
  } catch (error) {
    recordingStatus.textContent = `Microphone permission failed: ${error.message}`;
    activeStream?.getTracks().forEach((track) => track.stop());
    activeStream = null;
    if (mediaRecorder?.state === "recording") mediaRecorder.stop();
    recorderCard.classList.remove("recording");
    startRecordingButton.disabled = false;
    stopRecordingButton.disabled = true;
  }
}

function stopRecording() {
  if (recognition) {
    recognition.onend = null;
    recognition.stop();
    recognition = null;
  }
  if (mediaRecorder?.state === "recording") {
    mediaRecorder.stop();
  }
}

function startSpeechRecognition() {
  if (!SpeechRecognition) return;
  try {
    recognition = new SpeechRecognition();
    recognition.lang = "en-GB";
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.onresult = (event) => {
      let interim = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const transcript = event.results[index][0].transcript;
        if (event.results[index].isFinal) {
          speechText += `${transcript} `;
        } else {
          interim += transcript;
        }
      }
      transcriptInput.value = [recordingBaseText, speechText, interim]
        .filter((part) => part.trim().length > 0)
        .join(" ")
        .trim();
      recordingStatus.textContent = interim
        ? `Listening: ${interim}`
        : "Recording. Live transcript is updating.";
      refresh();
    };
    recognition.onerror = (event) => {
      recordingStatus.textContent = `Speech-to-text stopped: ${event.error}. Audio is still recording.`;
    };
    recognition.start();
  } catch (error) {
    recognition = null;
    recordingStatus.textContent =
      "Recording audio. Live speech-to-text could not start in this browser.";
  }
}

async function handleFileUpload(event) {
  const file = event.target.files?.[0];
  if (!file) return;

  const isText =
    file.type.startsWith("text/") ||
    /\.(txt|md|json)$/i.test(file.name);
  const isAudio = file.type.startsWith("audio/");

  if (isText) {
    transcriptInput.value = await file.text();
    recordingStatus.textContent = `Loaded transcript file: ${file.name}`;
    refresh();
    return;
  }

  if (isAudio) {
    audioPreview.src = URL.createObjectURL(file);
    audioPreview.hidden = false;
    recordingStatus.textContent =
      `Loaded audio file: ${file.name}. Browser upload preview works; paste its transcript below to check it.`;
    return;
  }

  recordingStatus.textContent = "Unsupported file. Upload a text transcript or an audio file.";
}

function clearAll() {
  transcriptInput.value = "";
  fileInput.value = "";
  audioPreview.removeAttribute("src");
  audioPreview.hidden = true;
  recordingStatus.textContent = "Cleared. Record, upload, or type a new transcript.";
  sampleButtons.forEach((button) => button.classList.remove("active"));
  refresh();
}

function looksLikeCard(value) {
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

startRecordingButton.addEventListener("click", startRecording);
stopRecordingButton.addEventListener("click", stopRecording);
clearButton.addEventListener("click", clearAll);
fileInput.addEventListener("change", handleFileUpload);
analyzeButton.addEventListener("click", refresh);
transcriptInput.addEventListener("input", refresh);
sampleButtons.forEach((button) => button.addEventListener("click", () => setSample(button.dataset.sample)));

if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
  recordingStatus.textContent =
    "Audio recording is unavailable in this browser. The transcript checker still works.";
  startRecordingButton.disabled = true;
}

setSample("password");
