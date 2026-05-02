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
    pattern: /\b(?:\d[ -]*?){13,19}\b/g
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

const severityPoints = {
  low: 10,
  medium: 22,
  high: 36,
  critical: 55
};

const severityRank = {
  low: 1,
  medium: 2,
  high: 3,
  critical: 4
};

const transcriptInput = document.querySelector("#transcriptInput");
const analyzeButton = document.querySelector("#analyzeButton");
const decisionEl = document.querySelector("#decision");
const scoreEl = document.querySelector("#score");
const summaryEl = document.querySelector("#summary");
const findingsEl = document.querySelector("#findings");
const safeTranscriptEl = document.querySelector("#safeTranscript");
const guidanceEl = document.querySelector("#guidance");
const heroDecision = document.querySelector("#heroDecision");
const heroSummary = document.querySelector("#heroSummary");
const sampleButtons = [...document.querySelectorAll("[data-sample]")];

function analyzeTranscript(text) {
  const findings = [];
  for (const rule of rules) {
    rule.pattern.lastIndex = 0;
    for (const match of text.matchAll(rule.pattern)) {
      findings.push({
        ...rule,
        start: match.index,
        end: match.index + match[0].length
      });
      if (rule.singleMatch) break;
    }
  }

  const sorted = removeOverlaps(findings);
  const score = Math.min(100, sorted.reduce((total, finding) => total + severityPoints[finding.severity], 0));
  const decision = decide(score, sorted);
  const safeTranscript = redact(text, sorted);
  return {
    decision,
    score,
    summary: summarize(decision, sorted),
    findings: sorted,
    safeTranscript,
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
    if (!overlaps) {
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
  safeTranscriptEl.textContent = result.safeTranscript;

  findingsEl.innerHTML = result.findings.length
    ? result.findings
        .map(
          (finding) => `
            <article class="finding ${finding.severity}">
              <strong>${finding.label} - ${finding.severity}</strong>
              <p>${finding.explanation}</p>
            </article>
          `
        )
        .join("")
    : `<article class="finding"><strong>No findings</strong><p>This transcript looks safe for a normal assistant response.</p></article>`;

  guidanceEl.innerHTML = result.guidance.map((item) => `<p>${item}</p>`).join("");
}

function setSample(name) {
  transcriptInput.value = samples[name];
  sampleButtons.forEach((button) => button.classList.toggle("active", button.dataset.sample === name));
  render(analyzeTranscript(transcriptInput.value));
}

analyzeButton.addEventListener("click", () => render(analyzeTranscript(transcriptInput.value)));
transcriptInput.addEventListener("input", () => render(analyzeTranscript(transcriptInput.value)));
sampleButtons.forEach((button) => button.addEventListener("click", () => setSample(button.dataset.sample)));

setSample("password");
