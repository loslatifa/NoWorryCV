const form = document.getElementById("tailor-form");
const submitButton = document.getElementById("submit-button");
const statusBox = document.getElementById("request-status");
const resultPlaceholder = document.getElementById("result-placeholder");
const resultRoot = document.getElementById("result-root");
const waitingPanel = document.getElementById("waiting-panel");
const progressFill = document.getElementById("progress-fill");
const progressPercent = document.getElementById("progress-percent");
const progressStage = document.getElementById("progress-stage");
const progressSteps = Array.from(document.querySelectorAll(".progress-step"));
const tipTitle = document.getElementById("tip-title");
const tipFocus = document.getElementById("tip-focus");
const tipBody = document.getElementById("tip-body");
const tipQuestion = document.getElementById("tip-question");
const tipKeywords = document.getElementById("tip-keywords");
const tipCounter = document.getElementById("tip-counter");
const tipPrev = document.getElementById("tip-prev");
const tipNext = document.getElementById("tip-next");
const tipsTrack = document.getElementById("tips-track");

const stageDefinitions = [
  { key: "queued", label: "任务排队中" },
  { key: "analyze_jd", label: "正在分析 JD 重点与招聘类型" },
  { key: "review_cards", label: "正在生成 JD 复习看板" },
  { key: "jd_review_doc", label: "正在整理 JD 复习文档" },
  { key: "parse_resume", label: "正在解析简历结构与事实卡片" },
  { key: "gap_analysis", label: "正在匹配经历、关键词和能力缺口" },
  { key: "strategy", label: "正在制定改写策略" },
  { key: "rewrite", label: "正在生成定制简历草稿" },
  { key: "review", label: "正在审查真实性与 ATS 结构" },
  { key: "refine_strategy", label: "正在根据审查结果微调策略" },
  { key: "finalize", label: "正在整理最终结果" },
  { key: "completed", label: "已完成" },
  { key: "failed", label: "执行失败" },
];

let pollTimer = null;
let tipItems = [];
let currentTipIndex = 0;
let reviewCardsSignature = "";

function setStatus(message, tone = "muted") {
  statusBox.textContent = message;
  statusBox.className = `request-status ${tone === "muted" ? "" : `is-${tone}`}`.trim();
}

function humanizeHiringTrack(value) {
  const mapping = {
    campus: "校招",
    experienced: "社招",
    intern: "实习",
    unknown: "未识别",
  };
  return mapping[value] || value || "-";
}

function renderList(targetId, items) {
  const target = document.getElementById(targetId);
  target.innerHTML = "";
  (items || []).forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    target.appendChild(li);
  });
}

function renderResult(result) {
  const latestReview = result.reviews[result.reviews.length - 1];
  document.getElementById("ats-score").textContent = latestReview?.ats_report?.score ?? "-";
  document.getElementById("risk-level").textContent = latestReview?.compliance_report?.risk_level ?? "-";
  document.getElementById("hiring-track").textContent = humanizeHiringTrack(result.jd_profile?.hiring_track);
  document.getElementById("stop-reason").textContent = result.stop_reason || "-";
  document.getElementById("fit-summary").textContent = result.final_package.fit_summary || "";
  document.getElementById("resume-markdown").textContent = result.final_package.draft.markdown || "";
  document.getElementById("jd-review-doc").textContent = result.final_package.jd_review_doc?.markdown || "";
  document.getElementById("interview-prep-doc").textContent = result.final_package.interview_prep_doc?.markdown || "";

  renderList("change-log", result.final_package.change_log || []);
  renderList("risk-notes", result.final_package.risk_notes || []);

  resultPlaceholder.classList.add("hidden");
  waitingPanel.classList.add("hidden");
  resultRoot.classList.remove("hidden");
}

function renderTipsTicker(items) {
  const repeated = [...items, ...items];
  tipsTrack.innerHTML = "";
  repeated.forEach((tip) => {
    const span = document.createElement("span");
    span.textContent = tip.ticker || tip.title;
    tipsTrack.appendChild(span);
  });
}

function renderCurrentTip() {
  if (!tipItems.length) return;
  const tip = tipItems[currentTipIndex % tipItems.length];
  tipTitle.textContent = tip.title;
  tipFocus.textContent = tip.focus_area || "岗位知识点";
  tipBody.textContent = [tip.why_it_matters, tip.review_tip || tip.body].filter(Boolean).join(" ");
  tipQuestion.textContent = tip.sample_question || "回想一个与你最相关的真实经历，准备在面试中讲清楚。";
  tipCounter.textContent = `${currentTipIndex + 1} / ${tipItems.length}`;
  tipKeywords.innerHTML = "";
  (tip.keywords || []).forEach((keyword) => {
    const chip = document.createElement("span");
    chip.textContent = keyword;
    tipKeywords.appendChild(chip);
  });
  tipPrev.disabled = tipItems.length <= 1;
  tipNext.disabled = tipItems.length <= 1;
}

function getStageLabel(stageKey) {
  return stageDefinitions.find((stage) => stage.key === stageKey)?.label || "正在处理中";
}

function getVisibleStageIndex(stageKey, progress) {
  if (progress === 100 || stageKey === "completed" || stageKey === "failed" || stageKey === "finalize") {
    return 4;
  }
  const mapping = {
    queued: 0,
    analyze_jd: 0,
    review_cards: 1,
    jd_review_doc: 1,
    parse_resume: 1,
    gap_analysis: 2,
    strategy: 2,
    rewrite: 3,
    refine_strategy: 3,
    review: 4,
  };
  return mapping[stageKey] ?? 0;
}

function updateProgressView(value, stageKey = "queued", statusMessage = "") {
  const progress = Math.max(0, Math.min(100, Math.round(value)));
  progressFill.style.width = `${progress}%`;
  progressPercent.textContent = `${progress}%`;
  progressStage.textContent = statusMessage || getStageLabel(stageKey);

  const stageIndex = getVisibleStageIndex(stageKey, progress);
  progressSteps.forEach((step, index) => {
    step.classList.toggle("active", index === stageIndex && progress < 100);
    step.classList.toggle("done", index < stageIndex || progress === 100);
  });
}

function startWaitingExperience(jdText) {
  resultRoot.classList.add("hidden");
  resultPlaceholder.classList.add("hidden");
  waitingPanel.classList.remove("hidden");
  reviewCardsSignature = "";
  tipItems = [
    {
      title: "JD 知识点整理中",
      focus_area: "等待生成",
      review_tip: "系统会先分析 JD 并生成复习卡片，再开始解析简历和改写策略。",
      sample_question: "你可以先想想：这个岗位最可能追问哪 2 到 3 个知识点？",
      keywords: jdText ? [jdText.slice(0, 18)] : [],
      ticker: "正在根据 JD 提炼复习卡片",
    },
  ];
  currentTipIndex = 0;
  renderCurrentTip();
  renderTipsTicker(tipItems);
  updateProgressView(5, "queued", "任务已创建，准备开始。");
}

function stopWaitingExperience(success = false) {
  if (pollTimer) {
    window.clearTimeout(pollTimer);
    pollTimer = null;
  }
  if (success) {
    updateProgressView(100, "completed", "简历定制完成。");
  }
}

function applyJobStatus(job) {
  updateProgressView(job.progress_percent ?? 0, job.current_stage || "queued", job.status_message || "");
  if (job.review_cards?.length) {
    maybeUpdateReviewCards(job.review_cards);
  }
  if (job.status === "running" || job.status === "queued") {
    setStatus(job.status_message || "任务运行中，请稍候。", "loading");
  }
}

function maybeUpdateReviewCards(cards) {
  const signature = JSON.stringify(cards || []);
  if (signature === reviewCardsSignature) return;
  reviewCardsSignature = signature;
  setReviewCards(cards);
}

function setReviewCards(cards) {
  const normalizedCards = (cards || []).map((card) => ({
    ...card,
    ticker: card.keywords?.length ? `${card.title}: ${card.keywords.join(" / ")}` : card.title,
  }));
  if (!normalizedCards.length) return;
  tipItems = normalizedCards;
  currentTipIndex = 0;
  renderCurrentTip();
  renderTipsTicker(tipItems);
}

function showPreviousTip() {
  if (tipItems.length <= 1) return;
  currentTipIndex = (currentTipIndex - 1 + tipItems.length) % tipItems.length;
  renderCurrentTip();
}

function showNextTip() {
  if (tipItems.length <= 1) return;
  currentTipIndex = (currentTipIndex + 1) % tipItems.length;
  renderCurrentTip();
}

async function pollRunStatus(runId, startedAt = Date.now()) {
  const response = await fetch(`/api/v1/tailor-runs/${runId}/status`);
  const job = await response.json();
  if (!response.ok) {
    throw new Error(job.detail || "任务状态获取失败。");
  }

  applyJobStatus(job);

  if (job.status === "completed") {
    return job.result;
  }
  if (job.status === "failed") {
    throw new Error(job.error_message || "任务执行失败。");
  }
  if (Date.now() - startedAt > 5 * 60 * 1000) {
    throw new Error("等待时间过长，请稍后刷新页面查看结果。");
  }

  return new Promise((resolve, reject) => {
    pollTimer = window.setTimeout(() => {
      pollRunStatus(runId, startedAt).then(resolve).catch(reject);
    }, 900);
  });
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const fileInput = document.getElementById("resume-file");
  if (!fileInput.files || !fileInput.files[0]) {
    setStatus("请先选择简历文件。", "error");
    return;
  }

  const formData = new FormData();
  formData.append("resume_file", fileInput.files[0]);
  formData.append("jd_text", document.getElementById("jd-text").value);
  formData.append("candidate_notes", document.getElementById("candidate-notes").value);
  formData.append("output_language", document.getElementById("output-language").value);
  formData.append("max_iterations", document.getElementById("max-iterations").value);

  submitButton.disabled = true;
  setStatus("正在创建任务并启动深度 Agent 模式，你可以在等待时复习下方 JD 知识点。", "loading");
  startWaitingExperience(document.getElementById("jd-text").value);

  try {
    const response = await fetch("/api/v1/tailor-runs/upload-jobs", {
      method: "POST",
      body: formData,
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "请求失败，请稍后重试。");
    }
    applyJobStatus(payload);
    const result = await pollRunStatus(payload.run_id);
    renderResult(result);
    setStatus("已生成定制简历，你可以继续修改 JD 或重新上传文件再跑一轮。", "success");
    stopWaitingExperience(true);
  } catch (error) {
    stopWaitingExperience(false);
    setStatus(error.message || "请求失败，请检查文件格式或后端配置。", "error");
  } finally {
    submitButton.disabled = false;
  }
});

tipPrev.addEventListener("click", showPreviousTip);
tipNext.addEventListener("click", showNextTip);
