const SESSION_KEY = "resumatch.session";
const EMPTY_ANALYSIS_MESSAGE =
  "Your match score, missing skills, and practice questions will appear here.";
const WATSON_CHAT_SCRIPT_SRC =
  "https://web-chat.global.assistant.watson.appdomain.cloud/versions/latest/WatsonAssistantChatEntry.js";
const WATSON_CHAT_CONFIG = Object.freeze({
  integrationID: "ecd74fbe-e97d-4762-a2fc-ed54a4017837",
  region: "au-syd",
  serviceInstanceID: "1b7c3b6d-06b8-4756-804f-31b10918d720"
});
let watsonChatBootstrapped = false;

const fallbackQuestions = [
  {
    category: "Introduction",
    text: "Walk me through your background and explain why this role is a strong match for you.",
    tip: "Use a short present-past-future structure. Mention your current skills, one relevant project, and why this role is the logical next step."
  },
  {
    category: "Job fit",
    text: "Which requirement in this job description best matches your strongest experience?",
    tip: "Name the requirement directly, give a concrete example, and connect the outcome to the employer's needs."
  },
  {
    category: "Project depth",
    text: "Tell me about a project where you had to learn quickly and deliver under a deadline.",
    tip: "Use the STAR method. Focus on the decision you made, the tradeoff involved, and the measurable result."
  }
];

document.addEventListener("DOMContentLoaded", () => {
  const page = document.body.dataset.page;

  if (page === "home") {
    initAnalyzerPage();
  }

  if (page === "practice") {
    initPracticePage();
  }

  initWatsonChatPreview();
});

function initAnalyzerPage() {
  const form = document.querySelector("#analyzerForm");
  const resumeFile = document.querySelector("#resumeFile");
  const fileLabel = document.querySelector("#fileLabel");
  const dropZone = document.querySelector("#dropZone");
  const uploadStatus = document.querySelector("#uploadStatus");
  const uploadProgress = document.querySelector("#uploadProgress");
  const resetBtn = document.querySelector("#resetBtn");
  const savedSession = getSession();
  let selectedResumeFile = null;

  if (savedSession) {
    renderAnalysis(savedSession);
  }

  resumeFile.addEventListener("change", () => {
    selectedResumeFile = resumeFile.files[0] || null;
    setUploadState({
      dropZone,
      fileLabel,
      uploadStatus,
      uploadProgress,
      file: selectedResumeFile,
      status: selectedResumeFile ? "selected" : "empty"
    });
  });

  ["dragenter", "dragover"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.add("dragging");
    });
  });

  ["dragleave", "drop"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.remove("dragging");
    });
  });

  dropZone.addEventListener("drop", (event) => {
    selectedResumeFile = event.dataTransfer.files[0] || null;

    if (!selectedResumeFile) {
      return;
    }

    setUploadState({
      dropZone,
      fileLabel,
      uploadStatus,
      uploadProgress,
      file: selectedResumeFile,
      status: "selected"
    });
  });

  resetBtn.addEventListener("click", () => {
    form.reset();
    selectedResumeFile = null;
    setUploadState({
      dropZone,
      fileLabel,
      uploadStatus,
      uploadProgress,
      file: null,
      status: "empty"
    });
    localStorage.removeItem(SESSION_KEY);
    document.querySelector("#analysisCard").classList.add("hidden");
    document.querySelector("#emptyState").classList.remove("hidden");
    setEmptyMessage(EMPTY_ANALYSIS_MESSAGE);
    showToast("Analyzer reset.");
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const file = selectedResumeFile || resumeFile.files[0];
    const description = document.querySelector("#jobDescription").value.trim();
    const role = document.querySelector("#targetRole").value.trim() || "Target role";
    const level = document.querySelector("#experienceLevel").value;
    const submitBtn = form.querySelector('button[type="submit"]');

    if (!file) {
      showToast("Please upload your resume first.");
      return;
    }

    if (description.length < 80) {
      showToast("Paste a fuller job description for better questions.");
      return;
    }

    setButtonLoading(submitBtn, true);

    try {
      const session = await analyzeWithBackend({
        file,
        description,
        role,
        level,
        onUploadProgress: (percent) => {
          setUploadState({
            dropZone,
            fileLabel,
            uploadStatus,
            uploadProgress,
            file,
            status: "uploading",
            percent
          });
        },
        onStatus: (status) => {
          setUploadState({
            dropZone,
            fileLabel,
            uploadStatus,
            uploadProgress,
            file,
            status
          });
        }
      });

      localStorage.setItem(SESSION_KEY, JSON.stringify(session));
      renderAnalysis(session);
      setUploadState({
        dropZone,
        fileLabel,
        uploadStatus,
        uploadProgress,
        file,
        status: "uploaded",
        percent: 100
      });
      showToast(
        session.source === "browser"
          ? "Practice questions generated locally."
          : "Gemini analysis complete."
      );
    } catch (error) {
      setUploadState({
        dropZone,
        fileLabel,
        uploadStatus,
        uploadProgress,
        file,
        status: "error"
      });
      renderAnalyzerError(error.message || "Could not analyze the resume.");
      showToast(error.message || "Could not analyze the resume.");
    } finally {
      setButtonLoading(submitBtn, false);
    }
  });
}

async function analyzeWithBackend({
  file,
  description,
  role,
  level,
  onUploadProgress = () => {},
  onStatus = () => {}
}) {
  if (window.location.protocol === "file:") {
    return {
      ...buildSession({ resumeName: file.name, description, role, level }),
      source: "browser"
    };
  }

  const formData = new FormData();
  formData.append("resume", file);
  formData.append("job_description", description);
  formData.append("target_role", role);
  formData.append("experience_level", level);

  const payload = await postAnalysisForm(formData, {
    onUploadProgress,
    onStatus
  });

  return {
    ...payload,
    description,
    createdAt: new Date().toISOString(),
    source: payload.source || "gemini"
  };
}

function postAnalysisForm(formData, { onUploadProgress, onStatus }) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();

    request.open("POST", "/api/analyze/");

    request.upload.addEventListener("loadstart", () => {
      onUploadProgress(0);
    });

    request.upload.addEventListener("progress", (event) => {
      if (!event.lengthComputable) {
        onStatus("uploading");
        return;
      }

      const percent = Math.max(1, Math.round((event.loaded / event.total) * 100));
      onUploadProgress(percent);
    });

    request.upload.addEventListener("load", () => {
      onUploadProgress(100);
      onStatus("processing");
    });

    request.addEventListener("load", () => {
      let payload = {};

      try {
        payload = JSON.parse(request.responseText || "{}");
      } catch (error) {
        reject(new Error("The backend returned an invalid response."));
        return;
      }

      if (request.status < 200 || request.status >= 300) {
        reject(new Error(payload.error || "The backend could not analyze this resume."));
        return;
      }

      resolve(payload);
    });

    request.addEventListener("error", () => {
      reject(new Error("Network error while uploading the resume."));
    });

    request.addEventListener("timeout", () => {
      reject(new Error("The analysis request timed out. Try again."));
    });

    request.timeout = 90000;
    request.send(formData);
  });
}

function buildSession({ resumeName, description, role, level }) {
  const keywords = extractKeywords(description);
  const score = calculateScore(description, keywords, resumeName);
  const questions = generateQuestions({ keywords, role, level });

  return {
    resumeName,
    description,
    role,
    level,
    keywords,
    score,
    questions,
    createdAt: new Date().toISOString()
  };
}

function extractKeywords(description) {
  const text = description.toLowerCase();
  const keywordMap = [
    ["JavaScript", ["javascript", "js", "typescript", "frontend"]],
    ["React", ["react", "redux", "next.js", "component"]],
    ["HTML/CSS", ["html", "css", "responsive", "accessibility"]],
    ["APIs", ["api", "rest", "graphql", "integration"]],
    ["Databases", ["sql", "database", "mongodb", "postgres"]],
    ["Cloud", ["aws", "azure", "gcp", "cloud", "deployment"]],
    ["Testing", ["test", "testing", "jest", "qa", "automation"]],
    ["Communication", ["communication", "stakeholder", "client", "collaborate"]],
    ["Problem solving", ["debug", "troubleshoot", "problem", "optimize"]],
    ["Leadership", ["lead", "mentor", "ownership", "manage"]]
  ];

  const found = keywordMap
    .filter(([, terms]) => terms.some((term) => text.includes(term)))
    .map(([label]) => label);

  return found.length ? found.slice(0, 6) : ["Role basics", "Projects", "Communication"];
}

function calculateScore(description, keywords, resumeName) {
  const lengthBoost = Math.min(14, Math.floor(description.length / 180));
  const keywordBoost = Math.min(20, keywords.length * 3);
  const fileBoost = resumeName.length % 7;

  return Math.min(96, 58 + lengthBoost + keywordBoost + fileBoost);
}

function generateQuestions({ keywords, role, level }) {
  const normalizedRole = role === "Target role" ? "this role" : role;
  const questions = [
    {
      category: "Opening",
      text: `Introduce yourself as a ${level.toLowerCase()} candidate for ${normalizedRole}. What should the interviewer remember about you?`,
      tip: "Keep it under 90 seconds. Connect your skills, projects, and motivation to the exact role."
    },
    {
      category: "Resume match",
      text: `Which resume project proves you can succeed in ${normalizedRole}, and what was your personal contribution?`,
      tip: "Pick one project. Explain the problem, your specific work, the tools used, and the result."
    }
  ];

  keywords.slice(0, 4).forEach((keyword) => {
    questions.push({
      category: keyword,
      text: `How would you explain your experience with ${keyword} using a real example from your resume?`,
      tip: `Mention what you built, why ${keyword} mattered, and how you would improve it if you repeated the project.`
    });
  });

  questions.push({
    category: "Scenario",
    text: "If the interviewer gives you a requirement you have never worked on before, how would you approach it?",
    tip: "Show a practical plan: clarify the goal, break the task down, research quickly, build a small version, then ask for feedback."
  });

  questions.push({
    category: "Closing",
    text: "What questions would you ask the interviewer to understand expectations for the first 90 days?",
    tip: "Ask about success metrics, team workflow, current pain points, and the projects that need attention first."
  });

  return questions.slice(0, 7);
}

function renderAnalysis(session) {
  const emptyState = document.querySelector("#emptyState");
  const analysisCard = document.querySelector("#analysisCard");
  const scoreRing = document.querySelector("#scoreRing");
  const scoreValue = document.querySelector("#scoreValue");
  const fitTitle = document.querySelector("#fitTitle");
  const fitSummary = document.querySelector("#fitSummary");
  const skillChips = document.querySelector("#skillChips");
  const questionPreview = document.querySelector("#questionPreview");

  emptyState.classList.add("hidden");
  analysisCard.classList.remove("hidden");
  setEmptyMessage(EMPTY_ANALYSIS_MESSAGE);

  scoreRing.style.setProperty("--score", `${session.score}%`);
  scoreValue.textContent = `${session.score}%`;
  fitTitle.textContent = `${session.role} readiness`;
  fitSummary.textContent =
    session.summary ||
    `${session.resumeName} was compared with the job description. Use these focus areas to practice sharper answers.`;

  skillChips.innerHTML = session.keywords
    .map((skill) => `<span class="chip">${escapeHtml(skill)}</span>`)
    .join("");

  questionPreview.innerHTML = session.questions
    .slice(0, 4)
    .map((question) => `<li>${escapeHtml(question.text)}</li>`)
    .join("");
}

function renderAnalyzerError(message) {
  const emptyState = document.querySelector("#emptyState");
  const analysisCard = document.querySelector("#analysisCard");

  analysisCard.classList.add("hidden");
  emptyState.classList.remove("hidden");
  setEmptyMessage(message);
}

function initPracticePage() {
  const session = getSession() || {
    role: "Target role",
    score: 0,
    keywords: ["Role basics", "Projects", "Communication"],
    questions: fallbackQuestions
  };

  let currentIndex = 0;
  const answerBox = document.querySelector("#answerBox");
  const tipBox = document.querySelector("#tipBox");
  const tipText = document.querySelector("#tipText");
  const toggleTip = document.querySelector("#toggleTip");
  const prevBtn = document.querySelector("#prevQuestion");
  const nextBtn = document.querySelector("#nextQuestion");

  document.querySelector("#sessionIntro").textContent =
    session.score > 0
      ? `Practicing for ${session.role}. Focus on proof, clarity, and job description alignment.`
      : "This is a starter set. Generate an analysis to unlock role specific practice.";

  document.querySelector("#statScore").textContent = session.score > 0 ? `${session.score}%` : "--";
  document.querySelector("#statCount").textContent = session.questions.length;
  document.querySelector("#topicStack").innerHTML = session.keywords
    .map((topic) => `<span class="chip">${escapeHtml(topic)}</span>`)
    .join("");

  function renderQuestion() {
    const question = session.questions[currentIndex];

    document.querySelector("#questionCounter").textContent =
      `Question ${currentIndex + 1} of ${session.questions.length}`;
    document.querySelector("#questionCategory").textContent = question.category;
    document.querySelector("#questionText").textContent = question.text;
    tipText.textContent = question.tip;
    answerBox.value = "";
    tipBox.classList.add("hidden");
    toggleTip.textContent = "Show guide";
    prevBtn.disabled = currentIndex === 0;
    nextBtn.innerHTML =
      currentIndex === session.questions.length - 1
        ? "Restart"
        : `Next
          <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path d="M5 12h14M13 6l6 6-6 6"></path>
          </svg>`;
  }

  prevBtn.addEventListener("click", () => {
    currentIndex = Math.max(0, currentIndex - 1);
    renderQuestion();
  });

  nextBtn.addEventListener("click", () => {
    currentIndex = currentIndex === session.questions.length - 1 ? 0 : currentIndex + 1;
    renderQuestion();
  });

  toggleTip.addEventListener("click", () => {
    const isHidden = tipBox.classList.toggle("hidden");
    toggleTip.textContent = isHidden ? "Show guide" : "Hide guide";
  });

  renderQuestion();
}

function getSession() {
  try {
    const rawSession = localStorage.getItem(SESSION_KEY);
    return rawSession ? JSON.parse(rawSession) : null;
  } catch (error) {
    localStorage.removeItem(SESSION_KEY);
    return null;
  }
}

function setUploadState({
  dropZone,
  fileLabel,
  uploadStatus,
  uploadProgress,
  file,
  status,
  percent = 0
}) {
  dropZone.classList.toggle("ready", Boolean(file) && status !== "error");
  dropZone.classList.toggle("error", status === "error");

  if (fileLabel) {
    fileLabel.textContent = file ? file.name : "Choose resume file";
  }

  if (uploadStatus) {
    uploadStatus.textContent = getUploadStatusText({ file, status, percent });
  }

  if (uploadProgress) {
    const shouldShowProgress = ["uploading", "processing", "uploaded"].includes(status);
    uploadProgress.classList.toggle("hidden", !shouldShowProgress);
    uploadProgress.value = status === "processing" ? 100 : percent;
    uploadProgress.textContent = `${uploadProgress.value}%`;
  }
}

function getUploadStatusText({ file, status, percent }) {
  if (!file || status === "empty") {
    return "No file selected";
  }

  if (status === "uploading") {
    return `Uploading ${file.name}... ${percent}%`;
  }

  if (status === "processing") {
    return "Upload complete. Gemini is analyzing your resume.";
  }

  if (status === "uploaded") {
    return `Uploaded ${file.name} (${formatFileSize(file.size)})`;
  }

  if (status === "error") {
    return `Could not analyze ${file.name}. Check the message on the right.`;
  }

  return `Selected ${file.name} (${formatFileSize(file.size)})`;
}

function formatFileSize(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "size unknown";
  }

  const units = ["B", "KB", "MB", "GB"];
  let size = bytes;
  let unitIndex = 0;

  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }

  return `${size.toFixed(size >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

function showToast(message) {
  const toast = document.querySelector("#toast");

  if (!toast) {
    return;
  }

  toast.textContent = message;
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 2600);
}

function setButtonLoading(button, isLoading) {
  if (!button) {
    return;
  }

  if (!button.dataset.originalHtml) {
    button.dataset.originalHtml = button.innerHTML;
  }

  button.disabled = isLoading;
  button.innerHTML = isLoading ? "Analyzing..." : button.dataset.originalHtml;
}

function setEmptyMessage(message) {
  const messageElement = document.querySelector("#emptyState p");

  if (messageElement) {
    messageElement.textContent = message;
  }
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function initWatsonChatPreview() {
  const preview = document.querySelector("[data-watson-chat-preview]");

  if (!preview) {
    return;
  }

  const root = preview.querySelector("[data-watson-chat-root]");
  const status = preview.querySelector("[data-watson-chat-status]");
  let didRender = false;

  if (!root) {
    return;
  }

  setWatsonChatStatus(status, "Loading Watson Assistant preview...", "loading");

  window.watsonAssistantChatOptions = {
    ...WATSON_CHAT_CONFIG,
    element: root,
    showLauncher: false,
    openChatByDefault: true,
    hideCloseButton: true,
    onLoad: async (instance) => {
      try {
        await instance.render();
        didRender = true;
        setWatsonChatStatus(status, "Watson Assistant is ready below.", "ready");
      } catch (error) {
        setWatsonChatStatus(
          status,
          "Watson Assistant could not render. Check the web chat integration settings.",
          "error"
        );
      }
    }
  };

  window.setTimeout(() => {
    if (!didRender) {
      setWatsonChatStatus(
        status,
        "Watson Assistant did not finish loading. A duplicate embed, blocked IBM script, or IBM-side web chat setting is likely stopping it.",
        "error"
      );
    }
  }, 12000);

  if (watsonChatBootstrapped) {
    return;
  }

  const script = document.createElement("script");
  script.src = WATSON_CHAT_SCRIPT_SRC;
  script.async = true;
  script.dataset.watsonChatLoader = "true";
  script.addEventListener("error", () => {
    setWatsonChatStatus(
      status,
      "Watson Assistant could not load. Check network access to IBM web chat.",
      "error"
    );
  });
  watsonChatBootstrapped = true;
  document.head.appendChild(script);
}

function setWatsonChatStatus(element, message, state) {
  if (!element) {
    return;
  }

  element.textContent = message;
  element.dataset.state = state;
}
