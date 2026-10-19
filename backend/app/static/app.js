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
const draftEditor = document.getElementById("draft-editor");
const resumeMarkdown = document.getElementById("resume-markdown");
const editorSaveStatus = document.getElementById("editor-save-status");
const editorRiskBanner = document.getElementById("editor-risk-banner");
const undoDraftButton = document.getElementById("undo-draft-button");
const redoDraftButton = document.getElementById("redo-draft-button");
const saveDraftButton = document.getElementById("save-draft-button");
const draftVersionSelect = document.getElementById("draft-version-select");
const restoreVersionButton = document.getElementById("restore-version-button");
const rewriteInstruction = document.getElementById("rewrite-instruction");
const draftDiffList = document.getElementById("draft-diff-list");
const diffSummary = document.getElementById("diff-summary");
const refreshDiffButton = document.getElementById("refresh-diff-button");
const exportFilename = document.getElementById("export-filename");
const copyPlainButton = document.getElementById("copy-plain-button");
const copyMarkdownButton = document.getElementById("copy-markdown-button");
const previewExportButton = document.getElementById("preview-export-button");
const exportDocxButton = document.getElementById("export-docx-button");
const exportPdfButton = document.getElementById("export-pdf-button");
const exportStatus = document.getElementById("export-status");
const exportOverflowWarning = document.getElementById("export-overflow-warning");
const exportPreviewShell = document.getElementById("export-preview-shell");
const exportPreviewFrame = document.getElementById("export-preview-frame");
const scoreStatus = document.getElementById("score-status");
const refreshScoreButton = document.getElementById("refresh-score-button");
const scoreDisclaimer = document.getElementById("score-disclaimer");
const scoreTruthBanner = document.getElementById("score-truth-banner");
const scoreComparison = document.getElementById("score-comparison");
const scoreDimensions = document.getElementById("score-dimensions");
const scoreKeywords = document.getElementById("score-keywords");
const scoreReasons = document.getElementById("score-reasons");
const confirmationPanel = document.getElementById("confirmation-panel");
const confirmationProgress = document.getElementById("confirmation-progress");
const structuredProfile = document.getElementById("structured-profile");
const followUpBlock = document.getElementById("follow-up-block");
const followUpList = document.getElementById("follow-up-list");
const followUpProgress = document.getElementById("follow-up-progress");
const factCardList = document.getElementById("fact-card-list");
const addFactButton = document.getElementById("add-fact-button");
const profileConfirmed = document.getElementById("profile-confirmed");
const backToUploadButton = document.getElementById("back-to-upload-button");
const confirmGenerateButton = document.getElementById("confirm-generate-button");
const privacyConsent = document.getElementById("privacy-consent");
const privacyRetentionHours = document.getElementById("privacy-retention-hours");
const taskRetention = document.getElementById("task-retention");
const deleteRunButton = document.getElementById("delete-run-button");
const cancelRunButton = document.getElementById("cancel-run-button");
const retryRunButton = document.getElementById("retry-run-button");
const jobAttemptStatus = document.getElementById("job-attempt-status");
const stageHistoryList = document.getElementById("stage-history-list");
const archiveSelect = document.getElementById("archive-select");
const newArchiveJobButton = document.getElementById("new-archive-job-button");
const editArchiveButton = document.getElementById("edit-archive-button");
const exportArchiveButton = document.getElementById("export-archive-button");
const deleteArchiveButton = document.getElementById("delete-archive-button");
const saveArchiveButton = document.getElementById("save-archive-button");
const archiveStorageConsent = document.getElementById("archive-storage-consent");
const archiveSaveStatus = document.getElementById("archive-save-status");
let archiveCredentials = [];
let selectedArchive = null;
let editingArchiveId = "";
let archiveSaving = false;
let runIsBusy = false;

let previewData = null;
let currentRunId = "";
let currentRunToken = "";
let currentRunExpiresAt = "";
let currentMaxUploadBytes = 5 * 1024 * 1024;
let currentDraft = null;
let draftVersions = [];
let activeVersionId = "";
let draftMutationInProgress = false;
let undoStack = [];
let redoStack = [];
let editBaseline = null;
let draftIsDirty = false;
let draftDiff = null;
let diffBaseDraft = null;
let diffDecisions = {};
let draftDiffIsStale = false;
let currentCandidateProfile = null;
let exportPreviewUrl = "";
let exportPreviewSnapshot = "";
let exportTemplateId = "ats_standard";
let scoreExplanation = null;
let scoreExplanationIsStale = false;

function runRequestHeaders(json = true) {
  const headers = {};
  if (json) headers["Content-Type"] = "application/json";
  if (currentRunToken) headers["X-Run-Token"] = currentRunToken;
  return headers;
}

function persistActiveRun() {
  if (!currentRunId || !currentRunToken) return;
  try {
    sessionStorage.setItem("noworrycv-active-run", JSON.stringify({
      runId: currentRunId,
      token: currentRunToken,
      expiresAt: currentRunExpiresAt,
    }));
  } catch (_error) {
    // The current tab can still finish the task when session storage is unavailable.
  }
  rememberCurrentRun();
}

function rememberCurrentRun() {
  if (!currentRunId || !currentRunToken) return;
  try {
    const saved = JSON.parse(localStorage.getItem("noworrycv-run-history") || "[]");
    const items = Array.isArray(saved) ? saved : [];
    const validItems = items.filter((item) => item.id !== currentRunId && item.expiresAt && new Date(item.expiresAt).getTime() > Date.now());
    validItems.unshift({id: currentRunId, token: currentRunToken, expiresAt: currentRunExpiresAt});
    localStorage.setItem("noworrycv-run-history", JSON.stringify(validItems.slice(0, 200)));
  } catch (_error) {
    // The current task remains accessible in this tab through session storage.
  }
  window.refreshRunHistory?.();
}

function clearActiveRun() {
  try {
    sessionStorage.removeItem("noworrycv-active-run");
  } catch (_error) {
    // Nothing else is required when browser storage is unavailable.
  }
}

function createIdempotencyKey() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return `run-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function loadPrivacySummary() {
  try {
    const response = await fetch("/api/v1/privacy");
    if (!response.ok) return;
    const summary = await response.json();
    privacyRetentionHours.textContent = String(summary.anonymous_retention_hours || 24);
    currentMaxUploadBytes = Number(summary.max_upload_bytes) || currentMaxUploadBytes;
  } catch (_error) {
    // Static fallback remains visible when the API is temporarily unavailable.
  }
}

const stageDefinitions = [
  { key: "queued", label: "任务排队中" },
  { key: "analyze_jd", label: "正在分析 JD 重点与招聘类型" },
  { key: "review_cards", label: "正在生成 JD 复习看板" },
  { key: "jd_review_doc", label: "正在整理 JD 复习文档" },
  { key: "parse_resume", label: "正在解析简历结构与事实卡片" },
  { key: "gap_analysis", label: "正在匹配经历、关键词和能力缺口" },
  { key: "strategy", label: "正在制定改写策略" },
  { key: "rewrite", label: "正在生成定制简历草稿" },
  { key: "review", label: "正在审查真实性与 JD 匹配度" },
  { key: "refine_strategy", label: "正在根据审查结果微调策略" },
  { key: "finalize", label: "正在整理最终结果" },
  { key: "completed", label: "已完成" },
  { key: "failed", label: "执行失败" },
];

let pollTimer = null;
let progressStreamController = null;
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

function valueOrEmpty(value) {
  return value ?? "";
}

function makeReviewField(label, value, fieldName) {
  const wrapper = document.createElement("label");
  wrapper.className = "field compact";
  const title = document.createElement("span");
  title.textContent = label;
  const input = document.createElement("input");
  input.type = "text";
  input.value = valueOrEmpty(value);
  input.dataset.field = fieldName;
  input.addEventListener("input", () => {
    profileConfirmed.checked = false;
    updateConfirmationState();
  });
  wrapper.append(title, input);
  return wrapper;
}

function renderStructuredGroup(title, kind, items, fields) {
  const group = document.createElement("section");
  group.className = "structured-group";
  const groupHeading = document.createElement("div");
  groupHeading.className = "structured-group-heading";
  const heading = document.createElement("h5");
  heading.textContent = title;
  const addEntry = document.createElement("button");
  addEntry.type = "button";
  addEntry.className = "secondary-button";
  addEntry.textContent = `新增${title}`;
  addEntry.addEventListener("click", () => {
    const profile = collectCandidateProfile();
    const entryId = createIdempotencyKey();
    const entry = kind === "projects" ? { id: entryId, name: "新项目", bullets: [], skills_used: [] }
      : kind === "education" ? { id: entryId, school: "新学校" }
        : { id: entryId, company: "新公司", bullets: [], skills_used: [], achievements: [] };
    profile[kind].push(entry);
    previewData.candidate_profile = profile;
    previewData.fact_cards = collectFactCards();
    renderStructuredProfile(profile);
    renderFactCards();
    profileConfirmed.checked = false;
    updateConfirmationState();
  });
  groupHeading.append(heading, addEntry);
  group.appendChild(groupHeading);

  items.forEach((item, index) => {
    const entry = document.createElement("div");
    const isExperience = kind === "work_experiences" || kind === "projects";
    entry.className = `structured-entry${isExperience ? " experience-review-card" : ""}`;
    entry.dataset.kind = kind;
    entry.dataset.index = String(index);
    entry.dataset.entryId = item.id;
    const metadata = document.createElement("div");
    metadata.className = "structured-entry-meta";
    fields.forEach(([label, fieldName]) => {
      metadata.appendChild(makeReviewField(label, item[fieldName], fieldName));
    });
    entry.appendChild(metadata);
    if (isExperience) {
      const facts = factsForExperience(kind, item.id);
      const paragraphLabel = document.createElement("label");
      paragraphLabel.className = "field experience-paragraph-field";
      const paragraphTitle = document.createElement("span");
      paragraphTitle.textContent = "经历正文";
      const paragraph = document.createElement("textarea");
      paragraph.className = "experience-paragraph";
      paragraph.rows = 5;
      paragraph.value = ExperienceParagraphs.paragraphFor(facts, item.review_paragraph);
      paragraph.placeholder = "用完整段落描述这段经历的职责、行动与成果。";
      paragraph.setAttribute("aria-label", `${kind === "projects" ? item.name : item.company || "工作经历"}完整正文`);
      paragraph.addEventListener("input", invalidateReview);
      paragraphLabel.append(paragraphTitle, paragraph);
      entry.appendChild(paragraphLabel);
      const sourceDetails = document.createElement("details");
      sourceDetails.className = "experience-source-details";
      const summary = document.createElement("summary");
      summary.textContent = "查看来源文字";
      const source = document.createElement("p");
      source.textContent = [...new Set(facts.map(fact => fact.source_excerpt || fact.text))].join(" ") || "来源：你的补充";
      sourceDetails.append(summary, source);
      entry.appendChild(sourceDetails);
    }
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "text-button danger-button";
    remove.textContent = "删除此经历及其内容";
    remove.addEventListener("click", () => {
      const profile = collectCandidateProfile();
      previewData.fact_cards = collectFactCards().filter((fact) => !fact.source_span.startsWith(`${kind}.${item.id}.`) && fact.source_span !== `${kind}.${item.id}`);
      profile[kind].splice(index, 1);
      previewData.candidate_profile = profile;
      renderStructuredProfile(profile);
      renderFactCards();
      profileConfirmed.checked = false;
      updateConfirmationState();
    });
    entry.appendChild(remove);
    group.appendChild(entry);
  });
  structuredProfile.appendChild(group);
}

function renderStructuredProfile(profile) {
  experienceReviewCache.clear();
  structuredProfile.innerHTML = "";
  renderStructuredGroup("工作经历", "work_experiences", profile.work_experiences, [
    ["公司", "company"],
    ["岗位", "title"],
    ["开始时间", "start_date"],
    ["结束时间", "end_date"],
  ]);
  renderStructuredGroup("项目经历", "projects", profile.projects, [
    ["项目名称", "name"],
    ["担任角色", "role"],
    ["开始时间", "start_date"],
    ["结束时间", "end_date"],
  ]);
  renderStructuredGroup("教育经历", "education", profile.education, [
    ["学校", "school"],
    ["学历", "degree"],
    ["专业", "field_of_study"],
    ["毕业时间", "graduation_date"],
  ]);

  if (!structuredProfile.children.length) {
    const empty = document.createElement("p");
    empty.className = "review-help";
    empty.textContent = "未解析到结构化经历；你仍可通过下方简历内容区补充信息。";
    structuredProfile.appendChild(empty);
  }
  refreshFollowUpOwners();
}

function collectCandidateProfile() {
  const profile = structuredClone(previewData.candidate_profile);
  profile.basics.name = document.getElementById("candidate-name").value.trim() || null;
  profile.basics.email = document.getElementById("candidate-email").value.trim() || null;
  profile.basics.phone = document.getElementById("candidate-phone").value.trim() || null;
  profile.basics.location = document.getElementById("candidate-location").value.trim() || null;
  profile.summary = document.getElementById("candidate-summary").value.trim();

  structuredProfile.querySelectorAll(".structured-entry").forEach((entry) => {
    const item = profile[entry.dataset.kind]?.[Number(entry.dataset.index)];
    if (!item) return;
    entry.querySelectorAll("input[data-field]").forEach((input) => {
      item[input.dataset.field] = input.value.trim() || null;
    });
    const paragraph = entry.querySelector(".experience-paragraph");
    if (paragraph) {
      const current = ExperienceParagraphs.displayText(paragraph.value);
      const baseline = ExperienceParagraphs.paragraphFor(factsForExperience(entry.dataset.kind, item.id), item.review_paragraph);
      item.review_paragraph = !item.review_paragraph && current === baseline ? null : current;
    }
  });
  return profile;
}

function factCategoryLabel(category) {
  const labels = {
    work_bullet: "工作内容",
    project_bullet: "项目内容",
    skill: "技能",
    education: "教育",
    certification: "证书",
    achievement: "补充成果",
    general: "补充内容",
  };
  return labels[category] || category || "事实";
}

// Keep individual source IDs for generation while editing skills in one place.
let skillReviewSources = new Map();
let experienceReviewCache = new Map();
const skillKey = (text) => text.trim().replace(/\s+/g, " ").toLowerCase();

function collectSkillFacts() {
  const editor = document.getElementById("review-skills");
  if (!editor) return [];
  const seen = new Set();
  return editor.value.split(/[\n,，、;；]+/).map((text) => text.trim()).filter((text) => {
    const key = skillKey(text);
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  }).map((text) => {
    const key = skillKey(text);
    let source = skillReviewSources.get(key);
    if (!source) {
      source = {
        id: `fact_skill_${createIdempotencyKey()}`, category: "skill", text,
        source_type: "user", source_span: "skills", source_excerpt: text,
        evidence_level: "user_confirmed", confidence: 1,
        allowed_operations: ["rewrite", "reorder", "highlight"],
      };
      skillReviewSources.set(key, source);
    }
    return { ...source, text, confirmed: profileConfirmed.checked };
  });
}

function factsForExperience(kind, id) {
  const prefix = `${kind}.${id}.bullets.`;
  return previewData.fact_cards.filter(fact => fact.source_span.startsWith(prefix));
}

function collectExperienceFacts() {
  return Array.from(structuredProfile.querySelectorAll(".experience-review-card")).flatMap(entry => {
    const kind = entry.dataset.kind;
    const id = entry.dataset.entryId;
    const text = ExperienceParagraphs.displayText(entry.querySelector(".experience-paragraph").value);
    const key = `${kind}.${id}`;
    let cached = experienceReviewCache.get(key);
    if (!cached || cached.text !== text) {
      cached = { text, facts: ExperienceParagraphs.reconcile(factsForExperience(kind, id), text, {
        kind, ownerId: id, createId: () => `fact_review_${createIdempotencyKey()}`,
      }) };
      experienceReviewCache.set(key, cached);
    }
    return cached.facts.map(fact => ({ ...fact, confirmed: profileConfirmed.checked }));
  });
}

function collectFactCards() {
  const entries = Array.from(factCardList.querySelectorAll(".fact-review-card")).map((cardElement) => {
    const original = previewData.fact_cards.find((card) => card.id === cardElement.dataset.factId) || {};
    const text = cardElement.querySelector("textarea").value.trim();
    const edited = text !== original.text;
    const category = cardElement.querySelector(".fact-category").value;
    const owner = cardElement.querySelector(".fact-owner")?.value || original.source_span || "user_added";
    return {
      ...original,
      id: cardElement.dataset.factId,
      category: category === "skill" ? "skill" : owner.startsWith("work_experiences.") ? "work_bullet"
        : owner.startsWith("projects.") ? "project_bullet" : category,
      text,
      confirmed: profileConfirmed.checked,
      source_span: category === "skill" ? "skills" : owner,
      // Edits become user supplied content rather than claiming verbatim extraction.
      ...(edited ? { source_type: "user", evidence_level: "user_confirmed", source_excerpt: text, confidence: 1 } : {}),
    };
  });
  return [...collectSkillFacts(), ...collectExperienceFacts(), ...entries];
}

function invalidateReview() {
  profileConfirmed.checked = false;
  updateConfirmationState();
}

function collectFollowUpAnswers() {
  return Array.from(followUpList.querySelectorAll(".follow-up-card")).map((card) => ({
    id: card.dataset.questionId,
    status: card.querySelector("select").value,
    answer: card.querySelector("textarea").value.trim(),
    suggestedCategory: card.dataset.suggestedCategory || "general",
    prompt: card.dataset.prompt || "",
    sourceSpan: card.querySelector(".follow-up-owner")?.value || `follow_up.${card.dataset.questionId}`,
  }));
}

function createExperienceOwner(sourceSpan, factId, unassignedSpan = null) {
  const owner = document.createElement("select");
  owner.className = "fact-owner";
  owner.setAttribute("aria-label", "内容所属经历或项目");
  const defaultOwner = document.createElement("option");
  defaultOwner.value = unassignedSpan || (sourceSpan.startsWith("work_experiences.") || sourceSpan.startsWith("projects.") ? "user_added" : sourceSpan);
  defaultOwner.textContent = "独立补充资料（未指定经历）";
  owner.appendChild(defaultOwner);
  ["work_experiences", "projects"].forEach(kind => {
    (previewData.candidate_profile[kind] || []).forEach(item => {
      const prefix = `${kind}.${item.id}.bullets.`;
      const option = document.createElement("option");
      option.value = sourceSpan.startsWith(prefix) ? sourceSpan : `${prefix}${factId}`;
      option.textContent = kind === "projects" ? `项目：${item.name}` : `工作：${item.company || "未命名公司"} · ${item.title || "未填写岗位"}`;
      option.selected = sourceSpan.startsWith(prefix);
      owner.appendChild(option);
    });
  });
  return owner;
}

function refreshFollowUpOwners() {
  followUpList.querySelectorAll(".follow-up-card").forEach(card => {
    const select = card.querySelector(".follow-up-owner");
    if (!select) return;
    const updated = createExperienceOwner(select.value, `follow_up_${card.dataset.questionId}`, `follow_up.${card.dataset.questionId}`);
    select.replaceChildren(...Array.from(updated.children));
  });
}

function renderFollowUpQuestions(questions) {
  followUpList.innerHTML = "";
  followUpBlock.open = false;
  if (!questions?.length) {
    followUpBlock.classList.add("hidden");
    return;
  }

  followUpBlock.classList.remove("hidden");
  questions.forEach((question) => {
    const article = document.createElement("article");
    article.className = "follow-up-card";
    article.dataset.questionId = question.id;
    article.dataset.suggestedCategory = question.suggested_category || "general";
    article.dataset.prompt = question.prompt;

    const header = document.createElement("div");
    header.className = "fact-card-head";
    const priority = document.createElement("span");
    priority.className = "question-priority";
    priority.textContent = "选填";
    const status = document.createElement("select");
    status.setAttribute("aria-label", "是否补充这项信息");
    [
      ["skipped", "本次不补充"],
      ["answered", "补充到简历资料"],
    ].forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      status.appendChild(option);
    });
    header.append(priority, status);

    const prompt = document.createElement("p");
    prompt.className = "follow-up-prompt";
    prompt.textContent = question.prompt;
    const reason = document.createElement("p");
    reason.className = "fact-source";
    reason.textContent = question.reason;
    const answer = document.createElement("textarea");
    answer.className = "hidden";
    answer.rows = 3;
    answer.placeholder = "补充你希望放入简历的场景、行动或结果。";
    answer.setAttribute("aria-label", "补充简历内容");
    const owner = createExperienceOwner(`follow_up.${question.id}`, `follow_up_${question.id}`);
    owner.classList.add("follow-up-owner", "hidden");
    owner.setAttribute("aria-label", "补充内容所属经历");

    status.addEventListener("change", () => {
      answer.classList.toggle("hidden", status.value !== "answered");
      owner.classList.toggle("hidden", status.value !== "answered");
      invalidateReview();
    });
    answer.addEventListener("input", invalidateReview);
    owner.addEventListener("change", invalidateReview);
    article.append(header, prompt, reason, answer, owner);
    followUpList.appendChild(article);
  });
}

function buildFactsFromFollowUpAnswers() {
  return collectFollowUpAnswers()
    .filter((item) => item.status === "answered" && item.answer)
    .map((item) => ({
      id: `fact_follow_up_${item.id}_${createIdempotencyKey()}`,
      category: item.sourceSpan.startsWith("work_experiences.") ? "work_bullet"
        : item.sourceSpan.startsWith("projects.") ? "project_bullet" : item.suggestedCategory,
      text: item.answer,
      source_type: "user",
      source_span: item.sourceSpan,
      source_excerpt: item.prompt,
      evidence_level: "user_confirmed",
      confidence: 1,
      confirmed: true,
      allowed_operations: ["rewrite", "reorder", "highlight"],
    }));
}

function updateConfirmationState() {
  const facts = previewData ? collectFactCards() : [];
  const followUps = collectFollowUpAnswers();
  const additions = followUps.filter((item) => item.status === "answered" && item.answer);
  const workCount = structuredProfile.querySelectorAll('[data-kind="work_experiences"]').length;
  const projectCount = structuredProfile.querySelectorAll('[data-kind="projects"]').length;
  confirmationProgress.textContent = `${workCount} 段工作 · ${projectCount} 个项目 · ${collectSkillFacts().length} 项技能`;
  followUpProgress.textContent = additions.length ? `已补充 ${additions.length} 项` : "选填，可直接继续";
  const ready = facts.length + additions.length > 0 && facts.every((fact) => fact.text)
    && followUps.every((item) => item.status !== "answered" || item.answer);
  confirmGenerateButton.disabled = !(ready && profileConfirmed.checked);
  saveArchiveButton.disabled = confirmGenerateButton.disabled || !archiveStorageConsent.checked || archiveSaving;
}

function renderFactCards() {
  factCardList.innerHTML = "";
  skillReviewSources = new Map();
  const skills = previewData.fact_cards.filter((fact) => fact.category === "skill");
  skills.forEach((fact) => {
    if (!skillReviewSources.has(skillKey(fact.text))) skillReviewSources.set(skillKey(fact.text), fact);
  });
  const skillsSection = document.createElement("section");
  skillsSection.className = "skill-review-section";
  const skillsLabel = document.createElement("label");
  skillsLabel.htmlFor = "review-skills";
  skillsLabel.textContent = "技能与工具";
  const skillsHelp = document.createElement("p");
  skillsHelp.id = "review-skills-help";
  skillsHelp.className = "review-help";
  skillsHelp.textContent = "技能、工具和语言集中编辑，用逗号或换行分隔。空格和斜杠会保留在技能名称中。";
  const skillsEditor = document.createElement("textarea");
  skillsEditor.id = "review-skills";
  skillsEditor.rows = 3;
  skillsEditor.placeholder = "例如：Python、SQL、Power BI、CI/CD、英语";
  skillsEditor.setAttribute("aria-describedby", skillsHelp.id);
  skillsEditor.value = Array.from(skillReviewSources.values()).map((fact) => fact.text).join("、");
  skillsEditor.addEventListener("input", invalidateReview);
  skillsSection.append(skillsLabel, skillsHelp, skillsEditor);
  factCardList.appendChild(skillsSection);

  const groups = new Map();
  const groupFor = (fact) => {
    for (const kind of ["work_experiences", "projects"]) {
      const item = previewData.candidate_profile[kind]?.find((entry) => fact.source_span.startsWith(`${kind}.${entry.id}.`));
      if (item) return [kind + item.id, kind === "projects" ? `项目 · ${item.name}` : `工作 · ${item.company || "未命名公司"} · ${item.title || "未填写岗位"}`];
    }
    return ["work_bullet", "project_bullet", "achievement", "general"].includes(fact.category)
      ? ["supplements", "补充资料（待指定经历）"] : [fact.category, factCategoryLabel(fact.category)];
  };
  previewData.fact_cards.filter((fact) => fact.category !== "skill"
    && !["work_experiences", "projects"].some(kind =>
      previewData.candidate_profile[kind]?.some(item => fact.source_span.startsWith(`${kind}.${item.id}.bullets.`))
    )).forEach((fact) => {
    const [key, label] = groupFor(fact);
    if (!groups.has(key)) {
      const section = document.createElement("section");
      section.className = "resume-review-group";
      const heading = document.createElement("h5");
      heading.textContent = label;
      section.appendChild(heading);
      factCardList.appendChild(section);
      groups.set(key, section);
    }
    const article = document.createElement("article");
    article.className = "fact-review-card";
    article.dataset.factId = fact.id;
    const textarea = document.createElement("textarea");
    textarea.rows = 2;
    textarea.value = fact.text;
    textarea.setAttribute("aria-label", `${label}内容`);

    const details = document.createElement("details");
    details.className = "fact-source-details";
    const summary = document.createElement("summary");
    summary.textContent = "查看来源与内容类型";
    const category = document.createElement("select");
    category.className = "fact-category";
    category.setAttribute("aria-label", "内容类型");
    ["work_bullet", "project_bullet", "skill", "education", "certification", "achievement", "general"].forEach((value) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = factCategoryLabel(value);
      option.selected = value === fact.category;
      category.appendChild(option);
    });
    const owner = createExperienceOwner(fact.source_span || "user_added", fact.id);
    const source = document.createElement("p");
    source.className = "fact-source";
    source.textContent = fact.source_type === "user" ? `你的补充：${fact.source_excerpt || fact.text}`
      : fact.source_excerpt ? `简历原文：${fact.source_excerpt}` : "来源：上传的简历";
    details.append(summary, category, source);

    const footer = document.createElement("div");
    footer.className = "fact-card-footer";
    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "text-button danger-button";
    deleteButton.textContent = "移除此条";
    deleteButton.addEventListener("click", () => {
      previewData.fact_cards = collectFactCards().filter((item) => item.id !== fact.id);
      profileConfirmed.checked = false;
      renderFactCards();
    });
    textarea.addEventListener("input", invalidateReview);
    const regroup = () => {
      const profile = collectCandidateProfile();
      const facts = collectFactCards();
      previewData.candidate_profile = profile;
      previewData.fact_cards = facts;
      profileConfirmed.checked = false;
      renderStructuredProfile(profile);
      renderFactCards();
    };
    category.addEventListener("change", regroup);
    owner.addEventListener("change", regroup);
    footer.append(details, deleteButton);
    article.append(textarea, owner, footer);
    groups.get(key).appendChild(article);
  });
  updateConfirmationState();
}

function renderConfirmation(payload) {
  previewData = structuredClone(payload);
  const knownSkills = new Set(previewData.fact_cards.filter((fact) => fact.category === "skill").map((fact) => skillKey(fact.text)));
  Object.values(previewData.candidate_profile.skills || {}).flat().forEach((text) => {
    if (knownSkills.has(skillKey(text))) return;
    knownSkills.add(skillKey(text));
    previewData.fact_cards.push({
      id: `fact_skill_${createIdempotencyKey()}`, category: "skill", text,
      source_type: "resume", source_span: "skills", source_excerpt: "",
      evidence_level: "explicit", confidence: 1, confirmed: false,
      allowed_operations: ["rewrite", "reorder", "highlight"],
    });
  });
  const basics = payload.candidate_profile.basics || {};
  document.getElementById("candidate-name").value = valueOrEmpty(basics.name);
  document.getElementById("candidate-email").value = valueOrEmpty(basics.email);
  document.getElementById("candidate-phone").value = valueOrEmpty(basics.phone);
  document.getElementById("candidate-location").value = valueOrEmpty(basics.location);
  document.getElementById("candidate-summary").value = valueOrEmpty(payload.candidate_profile.summary);
  profileConfirmed.checked = false;
  renderStructuredProfile(payload.candidate_profile);
  renderFollowUpQuestions(payload.follow_up_questions || []);
  renderFactCards();
  form.classList.add("hidden");
  waitingPanel.classList.add("hidden");
  confirmationPanel.classList.remove("hidden");
  document.body.classList.add("review-mode");
}

function cloneDraft(draft) {
  return JSON.parse(JSON.stringify(draft));
}

function draftSnapshot(draft = currentDraft) {
  return JSON.stringify(draft);
}

function beginDraftEdit() {
  editBaseline = cloneDraft(currentDraft);
}

function finishDraftEdit() {
  if (editBaseline && draftSnapshot(editBaseline) !== draftSnapshot(currentDraft)) {
    undoStack.push(editBaseline);
    redoStack = [];
  }
  editBaseline = null;
  updateDraftHistoryButtons();
}

function handleDraftInput(setter, value) {
  setter(value);
  currentDraft.markdown = buildDraftMarkdown(currentDraft);
  resumeMarkdown.textContent = currentDraft.markdown;
  markDraftDirty();
}

function wireDraftControl(control, setter) {
  control.addEventListener("focus", beginDraftEdit);
  control.addEventListener("input", () => handleDraftInput(setter, control.value));
  control.addEventListener("change", finishDraftEdit);
  control.addEventListener("blur", finishDraftEdit);
}

function createDraftField(label, value, setter, options = {}) {
  const wrapper = document.createElement("section");
  wrapper.className = "draft-field";
  const header = document.createElement("div");
  header.className = "draft-field-head";
  const title = document.createElement("strong");
  title.textContent = label;
  header.appendChild(title);
  if (options.rewriteTarget) {
    header.appendChild(createRewriteButton(options.rewriteTarget));
  }
  const control = options.multiline ? document.createElement("textarea") : document.createElement("input");
  if (!options.multiline) control.type = "text";
  if (options.rows) control.rows = options.rows;
  control.value = valueOrEmpty(value);
  wireDraftControl(control, setter);
  wrapper.append(header, control);
  return wrapper;
}

function createRewriteButton(targetType, sectionIndex = null, itemIndex = null) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "draft-rewrite-button";
  button.textContent = "AI 重写";
  button.addEventListener("click", () => rewriteDraftPart(targetType, sectionIndex, itemIndex, button));
  return button;
}

function renderDraftEditor() {
  if (!currentDraft) return;
  draftEditor.innerHTML = "";
  draftEditor.appendChild(
    createDraftField("标题", currentDraft.headline, (value) => {
      currentDraft.headline = value;
    }),
  );
  draftEditor.appendChild(
    createDraftField("个人摘要", currentDraft.summary, (value) => {
      currentDraft.summary = value;
    }, { multiline: true, rows: 4, rewriteTarget: "summary" }),
  );
  draftEditor.appendChild(
    createDraftField("技能（逗号或换行分隔）", currentDraft.skills_section.join(", "), (value) => {
      currentDraft.skills_section = value.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean);
    }, { multiline: true, rows: 3, rewriteTarget: "skills" }),
  );

  renderDraftSections("工作经历", "experience_section", "experience_bullet");
  renderDraftSections("项目经历", "project_section", "project_bullet");

  const education = document.createElement("section");
  education.className = "draft-field";
  const educationTitle = document.createElement("strong");
  educationTitle.textContent = "教育背景（每行一项）";
  const educationInput = document.createElement("textarea");
  educationInput.rows = 3;
  educationInput.value = currentDraft.education_section.join("\n");
  wireDraftControl(educationInput, (value) => {
    currentDraft.education_section = value.split("\n").map((item) => item.trim()).filter(Boolean);
  });
  education.append(educationTitle, educationInput);
  draftEditor.appendChild(education);
  resumeMarkdown.textContent = currentDraft.markdown || buildDraftMarkdown(currentDraft);
}

function renderDraftSections(label, sectionName, rewriteTarget) {
  const sections = currentDraft[sectionName] || [];
  if (!sections.length) return;
  const group = document.createElement("section");
  group.className = "draft-field";
  const groupTitle = document.createElement("strong");
  groupTitle.textContent = label;
  group.appendChild(groupTitle);

  sections.forEach((section, sectionIndex) => {
    const card = document.createElement("article");
    card.className = "draft-section-card";
    const meta = document.createElement("div");
    meta.className = "draft-section-meta";
    const heading = document.createElement("input");
    heading.type = "text";
    heading.value = valueOrEmpty(section.heading);
    heading.placeholder = "标题";
    wireDraftControl(heading, (value) => {
      currentDraft[sectionName][sectionIndex].heading = value;
    });
    const subheading = document.createElement("input");
    subheading.type = "text";
    subheading.value = valueOrEmpty(section.subheading);
    subheading.placeholder = "副标题";
    wireDraftControl(subheading, (value) => {
      currentDraft[sectionName][sectionIndex].subheading = value || null;
    });
    meta.append(heading, subheading);
    card.appendChild(meta);

    section.bullets.forEach((bullet, itemIndex) => {
      if (!bullet) return;
      const row = document.createElement("div");
      row.className = "draft-bullet-row";
      const textarea = document.createElement("textarea");
      textarea.rows = 3;
      textarea.value = bullet;
      wireDraftControl(textarea, (value) => {
        currentDraft[sectionName][sectionIndex].bullets[itemIndex] = value;
      });
      row.append(textarea, createRewriteButton(rewriteTarget, sectionIndex, itemIndex));
      card.appendChild(row);
    });
    group.appendChild(card);
  });
  draftEditor.appendChild(group);
}

function buildDraftMarkdown(draft) {
  const text = [draft.headline, draft.summary, ...(draft.skills_section || [])].join(" ");
  const zh = /[\u4e00-\u9fff]/.test(text);
  const labels = zh
    ? { summary: "个人摘要", skills: "技能", experience: "工作经历", projects: "项目经历", education: "教育背景" }
    : { summary: "Summary", skills: "Skills", experience: "Experience", projects: "Projects", education: "Education" };
  const lines = draft.headline ? [`# ${draft.headline}`] : [];
  if (draft.summary) lines.push("", `## ${labels.summary}`, draft.summary);
  if (draft.skills_section?.length) lines.push("", `## ${labels.skills}`, draft.skills_section.join(", "));
  appendDraftSections(lines, labels.experience, draft.experience_section || []);
  appendDraftSections(lines, labels.projects, draft.project_section || []);
  if (draft.education_section?.length) {
    lines.push("", `## ${labels.education}`, ...draft.education_section.map((item) => `- ${item}`));
  }
  return lines.join("\n").trim();
}

function buildDraftPlainText(draft) {
  const text = [draft.headline, draft.summary, ...(draft.skills_section || [])].join(" ");
  const zh = /[\u4e00-\u9fff]/.test(text);
  const labels = zh
    ? { summary: "个人摘要", skills: "技能", experience: "工作经历", projects: "项目经历", education: "教育背景" }
    : { summary: "Summary", skills: "Skills", experience: "Experience", projects: "Projects", education: "Education" };
  const basics = currentCandidateProfile?.basics || {};
  const lines = [];
  const title = draft.headline?.trim() || basics.name?.trim();
  if (title) lines.push(title);
  const contact = [basics.email, basics.phone, basics.location].filter(Boolean).join(" | ");
  if (contact) lines.push(contact);
  if (draft.summary?.trim()) lines.push("", labels.summary, draft.summary.trim());
  if (draft.skills_section?.length) lines.push("", labels.skills, draft.skills_section.filter(Boolean).join(", "));
  appendPlainSections(lines, labels.experience, draft.experience_section || []);
  appendPlainSections(lines, labels.projects, draft.project_section || []);
  const education = (draft.education_section || []).filter(Boolean);
  if (education.length) lines.push("", labels.education, ...education.map((item) => `- ${item}`));
  return lines.join("\n").trim();
}

function buildExportMarkdown(draft) {
  const markdown = buildDraftMarkdown(draft);
  const basics = currentCandidateProfile?.basics || {};
  const contact = [basics.email, basics.phone, basics.location].filter(Boolean).join(" | ");
  if (!contact) return markdown;
  const lines = markdown.split("\n");
  lines.splice(lines.length ? 1 : 0, 0, contact);
  return lines.join("\n");
}

function appendPlainSections(lines, label, sections) {
  if (!sections.length) return;
  lines.push("", label);
  sections.forEach((section) => {
    if (section.heading) lines.push(section.heading);
    if (section.subheading) lines.push(section.subheading);
    section.bullets.filter(Boolean).forEach((bullet) => lines.push(`- ${bullet}`));
  });
}

function sanitizeExportFilename(value) {
  const cleaned = (value || "")
    .trim()
    .replace(/\.(docx|pdf)$/i, "")
    .replace(/[\\/:*?"<>|\u0000-\u001f]/g, "-")
    .replace(/\s+/g, " ")
    .replace(/^[ .\-_]+|[ .\-_]+$/g, "")
    .slice(0, 80)
    .replace(/[ .\-_]+$/g, "");
  return cleaned || "tailored-resume";
}

function resetExportPreview() {
  if (exportPreviewUrl) URL.revokeObjectURL(exportPreviewUrl);
  exportPreviewUrl = "";
  exportPreviewSnapshot = "";
  exportPreviewFrame.removeAttribute("src");
  exportPreviewShell.classList.add("hidden");
  exportOverflowWarning.classList.add("hidden");
  exportDocxButton.disabled = true;
  exportPdfButton.disabled = true;
  exportStatus.textContent = "请先生成分页预览，确认内容没有溢出。";
}

function exportSnapshot() {
  return JSON.stringify({ run: currentRunId, draft: currentDraft, template: exportTemplateId });
}

document.getElementById("export-template-button").addEventListener("click", () => {
  openResumeTemplatePicker(exportTemplateId, value => {
    if (value === exportTemplateId) return;
    exportTemplateId = value;
    renderResumeTemplateSummary("export-template-summary", value);
    resetExportPreview();
    exportStatus.textContent = "模板已更换，请生成新的分页预览。";
  });
});

function invalidateExportPreview() {
  if (!exportPreviewSnapshot) return;
  exportPreviewSnapshot = "";
  exportDocxButton.disabled = true;
  exportPdfButton.disabled = true;
  exportOverflowWarning.classList.add("hidden");
  exportPreviewShell.classList.add("hidden");
  exportStatus.textContent = "简历内容已变化，请重新生成分页预览。";
}

async function copyText(value, successMessage) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
    } else {
      const control = document.createElement("textarea");
      control.value = value;
      control.setAttribute("readonly", "");
      control.style.position = "fixed";
      control.style.opacity = "0";
      document.body.appendChild(control);
      control.select();
      if (!document.execCommand("copy")) throw new Error("浏览器未允许复制。");
      control.remove();
    }
    exportStatus.textContent = successMessage;
  } catch (error) {
    exportStatus.textContent = error.message || "复制失败，请检查浏览器权限。";
  }
}

async function getResponseError(response, fallback) {
  try {
    const payload = await response.json();
    if (Array.isArray(payload.detail)) return payload.detail.map((item) => item.msg).join("；");
    return payload.detail || fallback;
  } catch (_error) {
    return fallback;
  }
}

async function previewResumeExport() {
  if (!currentRunId || !currentDraft) return;
  previewExportButton.disabled = true;
  exportDocxButton.disabled = true;
  exportPdfButton.disabled = true;
  exportStatus.textContent = "正在生成实际 PDF 分页预览…";
  exportOverflowWarning.classList.add("hidden");
  const snapshot = exportSnapshot();
  try {
    const response = await fetch(`/api/v1/tailor-runs/${currentRunId}/export-preview`, {
      method: "POST",
      headers: runRequestHeaders(),
      body: JSON.stringify({ draft: currentDraft, filename: sanitizeExportFilename(exportFilename.value), template: exportTemplateId }),
    });
    if (!response.ok) throw new Error(await getResponseError(response, "分页预览生成失败。"));
    const blob = await response.blob();
    if (snapshot !== exportSnapshot()) {
      exportStatus.textContent = "简历内容或模板已变化，请重新生成分页预览。";
      return;
    }
    if (exportPreviewUrl) URL.revokeObjectURL(exportPreviewUrl);
    exportPreviewUrl = URL.createObjectURL(blob);
    exportPreviewFrame.src = exportPreviewUrl;
    exportPreviewShell.classList.remove("hidden");
    const pageCount = Number(response.headers.get("X-Page-Count") || 1);
    const overflow = response.headers.get("X-Overflow") === "true";
    exportPreviewSnapshot = snapshot;
    exportDocxButton.disabled = false;
    exportPdfButton.disabled = false;
    const target = response.headers.get("X-Target-Pages");
    exportStatus.textContent = `预览共 ${pageCount} 页，${overflow ? "超出" : "符合"} ${target === "2" ? "2" : "1"} 页目标，可以检查后导出。DOCX 的分页可能因字体与软件不同而变化。`;
    if (overflow) {
      exportOverflowWarning.textContent = `当前内容会生成 ${pageCount} 页。建议精简摘要、技能或较弱的经历条目后重新预览。`;
      exportOverflowWarning.classList.remove("hidden");
    }
  } catch (error) {
    exportPreviewSnapshot = "";
    exportStatus.textContent = error.message || "分页预览生成失败。";
  } finally {
    previewExportButton.disabled = false;
  }
}

async function downloadResumeExport(format, button) {
  if (!currentRunId || !currentDraft) return;
  if (!exportPreviewSnapshot || exportPreviewSnapshot !== exportSnapshot()) {
    exportStatus.textContent = "请先为当前内容生成分页预览。";
    return;
  }
  button.disabled = true;
  exportStatus.textContent = `正在生成 ${format.toUpperCase()}…`;
  const filename = sanitizeExportFilename(exportFilename.value);
  const requestedSnapshot = exportSnapshot();
  try {
    const response = await fetch(`/api/v1/tailor-runs/${currentRunId}/export/${format}`, {
      method: "POST",
      headers: runRequestHeaders(),
      body: JSON.stringify({ draft: currentDraft, filename, template: exportTemplateId }),
    });
    if (!response.ok) throw new Error(await getResponseError(response, "导出失败。"));
    const blob = await response.blob();
    if (requestedSnapshot !== exportSnapshot()) throw new Error("简历内容或模板已变化，请重新预览后下载。");
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${filename}.${format}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
    exportStatus.textContent = `${format.toUpperCase()} 已生成并开始下载。`;
  } catch (error) {
    exportStatus.textContent = error.message || "导出失败。";
  } finally {
    button.disabled = !exportPreviewSnapshot || exportPreviewSnapshot !== exportSnapshot();
  }
}

function appendDraftSections(lines, label, sections) {
  if (!sections.length) return;
  lines.push("", `## ${label}`);
  sections.forEach((section) => {
    lines.push(`### ${section.heading}`);
    if (section.subheading) lines.push(section.subheading);
    section.bullets.filter(Boolean).forEach((bullet) => lines.push(`- ${bullet}`));
    lines.push("");
  });
}

function createScoreText(tagName, className, text) {
  const element = document.createElement(tagName);
  if (className) element.className = className;
  element.textContent = text;
  return element;
}

function signedScore(value) {
  const number = Number(value || 0);
  return number > 0 ? `+${number}` : String(number);
}

function markScoreExplanationStale() {
  if (!scoreExplanation) return;
  scoreExplanationIsStale = true;
  scoreStatus.textContent = "当前内容已变化；点击“重新计算评分”查看最新明细。";
  scoreStatus.classList.add("is-stale");
}

function renderScoreComparison(payload) {
  scoreComparison.innerHTML = "";
  const cards = [
    ["原始简历", payload.baseline.score, "score-baseline"],
    ["分数变化", signedScore(payload.score_delta), payload.score_delta >= 0 ? "score-positive" : "score-negative"],
    ["当前定制版本", payload.tailored.score, "score-tailored"],
  ];
  cards.forEach(([label, value, className]) => {
    const card = document.createElement("article");
    card.className = `score-total-card ${className}`;
    card.append(
      createScoreText("span", "", label),
      createScoreText("strong", "", value),
    );
    scoreComparison.appendChild(card);
  });
}

function renderScoreDimensions(payload) {
  scoreDimensions.innerHTML = "";
  const dimensions = [
    ["核心关键词", "core_keyword_score", "50%"],
    ["可选关键词", "optional_keyword_score", "10%"],
    ["结构完整度", "structure_score", "20%"],
    ["真实性", "truthfulness_score", "20%"],
  ];
  dimensions.forEach(([label, field, weight]) => {
    const baseline = Number(payload.baseline[field] || 0);
    const tailored = Number(payload.tailored[field] || 0);
    const card = document.createElement("article");
    card.className = "score-dimension-card";
    const header = document.createElement("div");
    header.className = "score-dimension-head";
    header.append(
      createScoreText("strong", "", label),
      createScoreText("span", "", `权重 ${weight}`),
    );
    card.appendChild(header);
    [["原始", baseline, "baseline"], ["当前", tailored, "tailored"]].forEach(([name, value, kind]) => {
      const row = document.createElement("div");
      row.className = "score-bar-row";
      const track = document.createElement("div");
      track.className = "score-bar-track";
      const fill = document.createElement("span");
      fill.className = `score-bar-fill ${kind}`;
      fill.style.width = `${Math.max(0, Math.min(100, value))}%`;
      track.appendChild(fill);
      row.append(
        createScoreText("span", "", name),
        track,
        createScoreText("strong", "", value),
      );
      card.appendChild(row);
    });
    const delta = tailored - baseline;
    card.appendChild(createScoreText("p", delta >= 0 ? "score-positive" : "score-negative", `变化 ${signedScore(delta)}`));
    scoreDimensions.appendChild(card);
  });
}

function renderScoreKeywords(report) {
  scoreKeywords.innerHTML = "";
  const groups = [
    ["核心关键词", "core"],
    ["可选关键词", "optional"],
  ];
  groups.forEach(([label, category]) => {
    const details = (report.keyword_details || []).filter((item) => item.category === category);
    const group = document.createElement("section");
    group.className = "score-keyword-group";
    const matchedCount = details.filter((item) => item.matched).length;
    group.appendChild(createScoreText("h5", "", `${label} · ${matchedCount}/${details.length} 命中`));
    if (!details.length) {
      group.appendChild(createScoreText("p", "review-help", "当前 JD 未提取此类关键词。"));
    }
    details.forEach((item) => {
      const entry = document.createElement("article");
      entry.className = `score-keyword-item ${item.matched ? "matched" : "missing"}`;
      const state = item.matched ? "已命中" : "未命中";
      entry.append(
        createScoreText("strong", "", item.keyword),
        createScoreText("span", "score-keyword-state", state),
        createScoreText(
          "p",
          "",
          item.locations?.length
            ? `位置：${item.locations.join("、")}`
            : "当前简历中未定位到该关键词。",
        ),
      );
      group.appendChild(entry);
    });
    scoreKeywords.appendChild(group);
  });
}

function renderScoreReasons(report) {
  scoreReasons.innerHTML = "";
  const reasonList = document.createElement("div");
  reasonList.className = "score-reason-list";
  (report.score_reasons || []).forEach((reason) => {
    const entry = document.createElement("article");
    entry.className = "score-reason-item";
    entry.append(
      createScoreText("strong", "score-impact", `+${reason.impact} 分`),
      createScoreText("p", "", reason.message),
      createScoreText("span", "review-help", `检查位置：${reason.location}`),
    );
    reasonList.appendChild(entry);
  });
  scoreReasons.appendChild(reasonList);

  const deductions = document.createElement("section");
  deductions.className = "score-deductions";
  deductions.appendChild(createScoreText("h5", "", "扣分与提醒"));
  if (report.deductions?.length) {
    const list = document.createElement("ul");
    report.deductions.forEach((item) => list.appendChild(createScoreText("li", "", item)));
    deductions.appendChild(list);
  } else {
    deductions.appendChild(createScoreText("p", "review-help", "当前未发现额外扣分项。"));
  }
  scoreReasons.appendChild(deductions);
}

function renderScoreExplanation(payload) {
  const risk = payload.compliance_report?.risk_level || "low";
  const unsupportedCount = payload.compliance_report?.unsupported_claims?.length || 0;
  scoreDisclaimer.textContent = payload.tailored.disclaimer;
  scoreTruthBanner.className = `score-truth-banner ${risk}`;
  if (risk === "low") {
    scoreTruthBanner.textContent = "真实性风险：低。当前版本的主要表述可追溯到已确认事实。";
  } else if (risk === "high") {
    scoreTruthBanner.textContent = `真实性风险：高。当前参考分不会覆盖此风险；${unsupportedCount} 条内容缺少事实溯源，请优先核验。`;
  } else {
    scoreTruthBanner.textContent = "真实性风险：中。当前参考分不会覆盖此风险；存在资历、表述强度或关键词支撑提醒，请优先查看扣分项。";
  }
  renderScoreComparison(payload);
  renderScoreDimensions(payload);
  renderScoreKeywords(payload.tailored);
  renderScoreReasons(payload.tailored);
}

async function loadScoreExplanation() {
  if (!currentRunId || !currentDraft) return;
  const requestedRunId = currentRunId;
  const requestedSnapshot = draftSnapshot();
  refreshScoreButton.disabled = true;
  scoreStatus.textContent = "正在计算原始简历与当前版本的分项对照…";
  scoreStatus.classList.remove("is-stale");
  try {
    const response = await fetch(`/api/v1/tailor-runs/${currentRunId}/score`, {
      method: "POST",
      headers: runRequestHeaders(),
      body: JSON.stringify({ draft: currentDraft }),
    });
    const payload = await response.json();
    if (requestedRunId !== currentRunId) return;
    if (!response.ok) throw new Error(payload.detail || "评分计算失败。");
    if (requestedSnapshot !== draftSnapshot()) {
      scoreStatus.textContent = "计算期间内容已变化，请重新计算评分。";
      scoreStatus.classList.add("is-stale");
      return;
    }
    scoreExplanation = payload;
    scoreExplanationIsStale = false;
    renderScoreExplanation(payload);
    document.getElementById("ats-score").textContent = payload.tailored.score;
    document.getElementById("risk-level").textContent = humanizeRiskLevel(payload.compliance_report.risk_level);
    scoreStatus.textContent = draftIsDirty
      ? "已按当前未保存内容计算；保存后会写入版本记录。"
      : "已按当前版本计算。";
  } catch (error) {
    if (requestedRunId !== currentRunId) return;
    scoreStatus.textContent = error.message || "评分计算失败。";
  } finally {
    if (requestedRunId === currentRunId) refreshScoreButton.disabled = false;
  }
}

function markDraftDirty(invalidateDiff = true) {
  draftIsDirty = true;
  editorSaveStatus.textContent = "有尚未保存的修改。";
  editorRiskBanner.textContent = "手工修改尚未重新审查；保存版本后会更新真实性风险和匹配分。";
  editorRiskBanner.className = "editor-risk-banner dirty";
  invalidateExportPreview();
  markScoreExplanationStale();
  if (draftDiff && invalidateDiff) {
    draftDiffIsStale = true;
    diffSummary.textContent = "当前内容已变化；点击“刷新对比”可重新计算差异。";
    draftDiffList.querySelectorAll(".diff-decision").forEach((button) => {
      button.disabled = true;
    });
  }
}

function updateDiffSummary() {
  if (!draftDiff) return;
  const rejectedCount = Object.values(diffDecisions).filter((value) => value === "rejected").length;
  const decisionText = rejectedCount ? `；已拒绝 ${rejectedCount} 项，当前草稿已实时更新` : "";
  diffSummary.textContent = `共 ${draftDiff.items.length} 项：改写 ${draftDiff.modified_count}、新增 ${draftDiff.added_count}、删除 ${draftDiff.removed_count}；${draftDiff.ungrounded_count} 项缺少事实来源${decisionText}。`;
}

function diffTypeLabel(changeType) {
  return { added: "新增", modified: "改写", removed: "删除" }[changeType] || changeType;
}

function addDiffText(container, text, emptyText = "—") {
  const paragraph = document.createElement("p");
  paragraph.textContent = text || emptyText;
  container.appendChild(paragraph);
}

function createEvidenceBlock(item) {
  const evidence = document.createElement("div");
  evidence.className = "diff-evidence hidden";
  const heading = document.createElement("strong");
  heading.textContent = "事实来源";
  evidence.appendChild(heading);
  if (item.source_excerpts?.length) {
    const list = document.createElement("ul");
    item.source_excerpts.forEach((excerpt, index) => {
      const entry = document.createElement("li");
      const factId = item.fact_ids?.[index];
      entry.textContent = factId ? `${excerpt}（${factId}）` : excerpt;
      list.appendChild(entry);
    });
    evidence.appendChild(list);
  } else {
    const message = document.createElement("p");
    message.textContent = "未找到可引用的事实卡来源；请人工确认该表达，或拒绝这项修改。";
    evidence.appendChild(message);
  }
  return evidence;
}

function createDiffSide(title, text, item, evidence, clickable = false) {
  const side = document.createElement("div");
  side.className = "diff-side";
  const label = document.createElement("span");
  label.textContent = title;
  side.appendChild(label);
  if (!clickable) {
    addDiffText(side, text);
    return side;
  }
  const button = document.createElement("button");
  button.type = "button";
  button.className = "diff-content-button";
  button.setAttribute("aria-expanded", "false");
  addDiffText(button, text);
  button.addEventListener("click", () => {
    const isHidden = evidence.classList.toggle("hidden");
    button.setAttribute("aria-expanded", String(!isHidden));
  });
  side.appendChild(button);
  return side;
}

function renderDraftDiff() {
  draftDiffList.innerHTML = "";
  const items = draftDiff?.items || [];
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "review-help";
    empty.textContent = "当前版本与原始内容没有可展示的差异。";
    draftDiffList.appendChild(empty);
    return;
  }

  items.forEach((item) => {
    const decision = diffDecisions[item.id] || "accepted";
    const card = document.createElement("article");
    card.className = `diff-card${decision === "rejected" ? " is-rejected" : ""}`;
    const head = document.createElement("div");
    head.className = "diff-card-head";
    const title = document.createElement("div");
    title.className = "diff-card-title";
    const badge = document.createElement("span");
    badge.className = `diff-badge ${item.change_type}`;
    badge.textContent = diffTypeLabel(item.change_type);
    const label = document.createElement("strong");
    label.textContent = item.label;
    title.append(badge, label);
    const state = document.createElement("span");
    state.className = "review-help";
    state.textContent = !diffDecisions[item.id] ? "待确认（暂保留）" : decision === "accepted" ? "已接受" : "已拒绝";
    head.append(title, state);

    const evidence = createEvidenceBlock(item);
    const columns = document.createElement("div");
    columns.className = "diff-columns";
    const originalClickable = item.change_type === "removed";
    columns.append(
      createDiffSide(originalClickable ? "原文 · 点击查看来源" : "原文", item.original_text, item, evidence, originalClickable),
      createDiffSide(originalClickable ? "定制版本" : "定制版本 · 点击查看来源", item.revised_text, item, evidence, !originalClickable),
    );

    const warning = document.createElement("p");
    warning.className = `diff-warning ${item.risk_level}`;
    warning.textContent = item.risk_message || "请确认这项修改。";

    const actions = document.createElement("div");
    actions.className = "diff-actions";
    const accept = document.createElement("button");
    accept.type = "button";
    accept.className = `diff-decision${diffDecisions[item.id] === "accepted" ? " is-selected" : ""}`;
    accept.disabled = draftDiffIsStale;
    accept.textContent = item.change_type === "removed" ? "保持删除" : "保留改写";
    accept.addEventListener("click", () => decideDraftDiff(item.id, "accepted"));
    const reject = document.createElement("button");
    reject.type = "button";
    reject.className = `diff-decision${decision === "rejected" ? " is-selected" : ""}`;
    reject.disabled = draftDiffIsStale;
    reject.textContent = item.change_type === "removed"
      ? "恢复原文"
      : item.change_type === "added" ? "删除新增" : "使用原文";
    reject.addEventListener("click", () => decideDraftDiff(item.id, "rejected"));
    actions.append(accept, reject);
    card.append(head, columns, warning, evidence, actions);
    if (window.buildChangeFeedback) card.append(window.buildChangeFeedback(item, draftDiff.version_id, currentRunId));
    draftDiffList.appendChild(card);
  });
}

function restoreRemovedDiffItem(draft, item) {
  if (item.target_type === "skill_removed") {
    if (item.original_text && !draft.skills_section.includes(item.original_text)) {
      draft.skills_section.push(item.original_text);
    }
    return;
  }
  if (item.target_type === "education_removed") {
    if (item.original_text && !draft.education_section.includes(item.original_text)) {
      draft.education_section.push(item.original_text);
    }
    return;
  }
  const sectionName = item.target_type === "experience_removed"
    ? "experience_section"
    : item.target_type === "project_removed" ? "project_section" : "";
  if (!sectionName || !item.original_text) return;
  let section = draft[sectionName][item.restore_section_index];
  if (!section) {
    section = {
      heading: sectionName === "experience_section" ? "恢复的工作经历" : "恢复的项目经历",
      subheading: null,
      bullets: [],
    };
    draft[sectionName].push(section);
  }
  if (section.bullets.includes(item.original_text)) return;
  section.bullets.push(item.original_text);
  const sectionIndex = draft[sectionName].indexOf(section);
  const span = `${sectionName}.${sectionIndex + 1}.bullets.${section.bullets.length}`;
  draft.traceability = (draft.traceability || []).filter((record) => record.draft_span !== span);
  draft.traceability.push({ draft_span: span, fact_ids: item.fact_ids || [] });
}

function rejectDraftDiffItem(draft, item) {
  if (item.change_type === "removed") {
    restoreRemovedDiffItem(draft, item);
    return;
  }
  if (item.target_type === "summary" || item.target_type === "headline") {
    draft[item.target_type] = item.original_text;
    return;
  }
  if (item.target_type === "skill") {
    draft.skills_section[item.item_index] = item.original_text;
    return;
  }
  if (item.target_type === "education") {
    draft.education_section[item.item_index] = item.original_text;
    return;
  }
  const sectionName = item.target_type === "experience_bullet"
    ? "experience_section"
    : item.target_type === "project_bullet" ? "project_section" : "";
  const section = sectionName ? draft[sectionName]?.[item.section_index] : null;
  if (section) section.bullets[item.item_index] = item.original_text;
}

function rebuildDraftFromDiffDecisions() {
  const rebuilt = cloneDraft(diffBaseDraft);
  (draftDiff?.items || []).forEach((item) => {
    if (diffDecisions[item.id] === "rejected") rejectDraftDiffItem(rebuilt, item);
  });
  rebuilt.skills_section = rebuilt.skills_section.filter(Boolean);
  rebuilt.education_section = rebuilt.education_section.filter(Boolean);
  rebuilt.markdown = buildDraftMarkdown(rebuilt);
  return rebuilt;
}

function decideDraftDiff(itemId, decision) {
  if (!currentDraft || !diffBaseDraft || diffDecisions[itemId] === decision) return;
  window.recordQualityDecision?.(currentRunId, draftDiff.version_id, itemId, decision);
  const before = cloneDraft(currentDraft);
  diffDecisions[itemId] = decision;
  const next = rebuildDraftFromDiffDecisions();
  const changed = JSON.stringify({ ...before, markdown: "" }) !== JSON.stringify({ ...next, markdown: "" });
  if (changed) {
    undoStack.push(before);
    redoStack = [];
  }
  currentDraft = changed ? next : before;
  renderDraftEditor();
  if (changed) markDraftDirty(false);
  renderDraftDiff();
  updateDiffSummary();
  updateDraftHistoryButtons();
}

async function loadDraftDiff() {
  if (!currentRunId || !currentDraft) return;
  const requestedRunId = currentRunId;
  const requestedSnapshot = draftSnapshot();
  refreshDiffButton.disabled = true;
  diffSummary.textContent = "正在生成逐条差异…";
  try {
    const response = await fetch(`/api/v1/tailor-runs/${currentRunId}/draft-diff`, {
      method: "POST",
      headers: runRequestHeaders(),
      body: JSON.stringify({ draft: currentDraft }),
    });
    const payload = await response.json();
    if (requestedRunId !== currentRunId) return;
    if (!response.ok) throw new Error(payload.detail || "差异生成失败。");
    if (requestedSnapshot !== draftSnapshot()) {
      draftDiffIsStale = true;
      diffSummary.textContent = "计算期间内容已变化，请刷新对比。";
      return;
    }
    draftDiff = payload;
    diffBaseDraft = cloneDraft(currentDraft);
    diffDecisions = {};
    draftDiffIsStale = false;
    updateDiffSummary();
    renderDraftDiff();
  } catch (error) {
    if (requestedRunId !== currentRunId) return;
    draftDiff = null;
    draftDiffIsStale = false;
    diffSummary.textContent = error.message || "差异生成失败。";
    draftDiffList.innerHTML = "";
  } finally {
    if (requestedRunId === currentRunId) refreshDiffButton.disabled = false;
  }
}

function updateDraftHistoryButtons() {
  undoDraftButton.disabled = undoStack.length === 0;
  redoDraftButton.disabled = redoStack.length === 0;
}

function renderVersionOptions() {
  draftVersionSelect.innerHTML = "";
  [...draftVersions].reverse().forEach((version) => {
    const option = document.createElement("option");
    option.value = version.id;
    const time = version.created_at ? new Date(version.created_at).toLocaleString() : "";
    option.textContent = `${version.label}${version.id === activeVersionId ? " · 当前" : ""}${version.archived ? " · 已归档" : ""}${time ? ` · ${time}` : ""}`;
    draftVersionSelect.appendChild(option);
  });
  if (activeVersionId) draftVersionSelect.value = activeVersionId;
  window.updateVersionManagement?.();
}

function applyReviewedVersion(version, versions) {
  currentDraft = cloneDraft(version.draft);
  draftVersions = versions || draftVersions;
  activeVersionId = version.id;
  window.changeQualityVersion?.(version);
  window.initializeInterviewPractice?.(currentRunId, activeVersionId);
  window.initializePositionLink?.(currentRunId, activeVersionId);
  window.initializeMaterials?.(currentRunId, activeVersionId);
  draftIsDirty = false;
  renderDraftEditor();
  renderVersionOptions();
  const risk = version.compliance_report?.risk_level || "low";
  editorRiskBanner.textContent = `真实性风险：${humanizeRiskLevel(risk)}；JD 匹配参考分：${version.ats_report?.score ?? "-"}。`;
  editorRiskBanner.className = `editor-risk-banner ${risk}`;
  editorSaveStatus.textContent = version.label || "版本已保存。";
  document.getElementById("risk-level").textContent = humanizeRiskLevel(risk);
  document.getElementById("ats-score").textContent = version.ats_report?.score ?? "-";
  resetExportPreview();
  loadDraftDiff();
  loadScoreExplanation();
  window.refreshRunHistory?.();
}

function initializeDraftEditor(result) {
  currentRunId = result.run_id;
  exportTemplateId = result.preferences?.template || "ats_standard";
  preferencesReady.then(() => {
    if (currentRunId === result.run_id) renderResumeTemplateSummary("export-template-summary", exportTemplateId);
  }).catch(() => {});
  currentCandidateProfile = result.candidate_profile || { basics: {} };
  currentDraft = cloneDraft(result.final_package.draft);
  draftVersions = result.draft_versions || [];
  activeVersionId = result.active_version_id || draftVersions[draftVersions.length - 1]?.id || "";
  window.initializeQualityFeedback?.(result.run_id, activeVersionId, result.provenance, result.provenance_history, draftVersions.find(version => version.id === activeVersionId));
  window.initializeInterviewPractice?.(result.run_id, activeVersionId);
  window.initializePositionLink?.(result.run_id, activeVersionId);
  window.initializeMaterials?.(result.run_id, activeVersionId);
  if (!draftVersions.length) {
    const latestReview = result.reviews[result.reviews.length - 1];
    draftVersions = [{
      id: "initial",
      created_at: "",
      source: "generated",
      label: "AI 生成版本",
      draft: cloneDraft(currentDraft),
      compliance_report: latestReview.compliance_report,
      ats_report: latestReview.ats_report,
    }];
  }
  undoStack = [];
  redoStack = [];
  draftIsDirty = false;
  scoreExplanation = null;
  scoreExplanationIsStale = false;
  scoreComparison.innerHTML = "";
  scoreDimensions.innerHTML = "";
  scoreKeywords.innerHTML = "";
  scoreReasons.innerHTML = "";
  renderDraftEditor();
  renderVersionOptions();
  updateDraftHistoryButtons();
  const latestVersion = draftVersions.find((item) => item.id === activeVersionId) || draftVersions[draftVersions.length - 1];
  const risk = latestVersion.compliance_report?.risk_level || "low";
  editorRiskBanner.textContent = `真实性风险：${humanizeRiskLevel(risk)}；JD 匹配参考分：${latestVersion.ats_report?.score ?? "-"}。`;
  editorRiskBanner.className = `editor-risk-banner ${risk}`;
  editorSaveStatus.textContent = latestVersion.label || "版本已保存。";
  document.getElementById("risk-level").textContent = humanizeRiskLevel(risk);
  document.getElementById("ats-score").textContent = latestVersion.ats_report?.score ?? "-";
  const candidateName = currentCandidateProfile.basics?.name?.trim();
  exportFilename.value = candidateName ? `${candidateName}-定制简历` : "定制简历";
  resetExportPreview();
  loadDraftDiff();
  loadScoreExplanation();
}

async function saveCurrentDraft(label = "手工保存") {
  if (draftMutationInProgress) return;
  draftMutationInProgress = true;
  saveDraftButton.disabled = true;
  editorSaveStatus.textContent = "正在保存并重新审查…";
  try {
    const response = await fetch(`/api/v1/tailor-runs/${currentRunId}/draft`, {
      method: "PUT",
      headers: runRequestHeaders(),
      body: JSON.stringify({ draft: currentDraft, label: document.getElementById("version-label").value.trim() || label }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "保存失败。");
    applyReviewedVersion(payload.version, payload.versions);
  } catch (error) {
    editorSaveStatus.textContent = error.message || "保存失败。";
  } finally {
    draftMutationInProgress = false;
    saveDraftButton.disabled = false;
  }
}

async function rewriteDraftPart(targetType, sectionIndex, itemIndex, button) {
  if (draftMutationInProgress) return;
  draftMutationInProgress = true;
  const before = cloneDraft(currentDraft);
  button.disabled = true;
  button.textContent = "重写中…";
  editorSaveStatus.textContent = "正在局部重写并审查…";
  try {
    const response = await fetch(`/api/v1/tailor-runs/${currentRunId}/rewrite-part`, {
      method: "POST",
      headers: runRequestHeaders(),
      body: JSON.stringify({
        draft: currentDraft,
        target_type: targetType,
        section_index: sectionIndex,
        item_index: itemIndex,
        instruction: rewriteInstruction.value.trim() || "在不新增事实的前提下，使表达更简洁、具体。",
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "局部重写失败。");
    undoStack.push(before);
    redoStack = [];
    applyReviewedVersion(payload.version, payload.versions);
    updateDraftHistoryButtons();
  } catch (error) {
    editorSaveStatus.textContent = error.message || "局部重写失败。";
    button.disabled = false;
    button.textContent = "AI 重写";
  } finally {
    draftMutationInProgress = false;
  }
}

function humanizeRiskLevel(value) {
  return { low: "低风险", medium: "中等风险", high: "高风险" }[value] || "待核验";
}

function renderResult(result) {
  preferencesReady.then(() => {
    setPreferences({ ...result.preferences, language: result.resolved_language === "zh" || result.resolved_language === "en" ? result.resolved_language : "auto" });
    const detected = result.detected_jd_profile;
    const detection = detected ? ` 原始识别：${humanizeHiringTrack(detected.hiring_track)} / ${detected.seniority || "unknown"}；生成采用：${humanizeHiringTrack(result.jd_profile.hiring_track)} / ${result.jd_profile.seniority || "unknown"}。` : "";
    document.getElementById("effective-preferences").textContent = `本版本偏好：${describePreferences(result.preferences)}；实际语言：${result.resolved_language}。${detection}`;
  }).catch(() => {});
  document.body.classList.remove("review-mode");
  form.classList.remove("hidden");
  const latestReview = result.reviews[result.reviews.length - 1];
  document.getElementById("ats-score").textContent = latestReview?.ats_report?.score ?? "-";
  document.getElementById("risk-level").textContent = humanizeRiskLevel(latestReview?.compliance_report?.risk_level);
  document.getElementById("hiring-track").textContent = humanizeHiringTrack(result.jd_profile?.hiring_track);
  document.getElementById("stop-reason").textContent = {
    quality_threshold_met: "达到优化标准",
    max_iterations_reached: "达到设定轮数",
    score_plateau: "匹配分变化较小",
  }[result.stop_reason] || "生成完成";
  document.getElementById("fit-summary").textContent = result.final_package.fit_summary || "";
  initializeDraftEditor(result);
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

function renderStageHistory(records) {
  stageHistoryList.innerHTML = "";
  if (!records?.length) {
    stageHistoryList.textContent = "尚无已完成阶段。";
    return;
  }
  records.forEach((record) => {
    const item = document.createElement("div");
    item.className = `stage-history-item ${record.status}`;
    const label = document.createElement("strong");
    label.textContent = getStageLabel(record.stage);
    const meta = document.createElement("span");
    const duration = record.duration_ms ? `${(record.duration_ms / 1000).toFixed(1)} 秒` : "未记录耗时";
    meta.textContent = record.status === "failed"
      ? `第 ${record.attempt} 次尝试 · 失败`
      : `第 ${record.attempt} 次尝试 · ${duration}`;
    item.append(label, meta);
    stageHistoryList.appendChild(item);
  });
}

function startWaitingExperience(jdText) {
  runIsBusy = true;
  syncArchiveControls();
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
  cancelRunButton.classList.remove("hidden");
  cancelRunButton.disabled = false;
  retryRunButton.classList.add("hidden");
  jobAttemptStatus.textContent = "等待持久化队列调度。";
  renderStageHistory([]);
}

function stopWaitingExperience(success = false) {
  progressStreamController?.abort();
  runIsBusy = false;
  syncArchiveControls();
  window.refreshRunHistory?.();
  if (pollTimer) {
    window.clearTimeout(pollTimer);
    pollTimer = null;
  }
  if (success) {
    updateProgressView(100, "completed", "简历定制完成。");
  }
}

function applyJobStatus(job) {
  document.getElementById("editor-job-context").textContent = `当前任务：${job.target_company || "未填写公司"} · ${job.target_job_title || job.result?.jd_profile?.job_title || "待识别岗位"}`;
  document.getElementById("current-task-jd").textContent = job.jd_text || "此旧任务未保留完整 JD，请参考岗位分析。";
  updateProgressView(job.progress_percent ?? 0, job.current_stage || "queued", job.status_message || "");
  if (job.review_cards?.length) {
    maybeUpdateReviewCards(job.review_cards);
  }
  if (job.status === "running" || job.status === "queued") {
    setStatus(job.status_message || "任务运行中，请稍候。", "loading");
    cancelRunButton.classList.remove("hidden");
    retryRunButton.classList.add("hidden");
    jobAttemptStatus.textContent = `第 ${Math.max(1, job.attempt_count || 1)} / ${job.max_attempts || 3} 次尝试；页面刷新后仍可继续查看。`;
  } else if (job.status === "failed" || job.status === "cancelled") {
    cancelRunButton.classList.add("hidden");
    retryRunButton.classList.toggle("hidden", !job.retryable);
    const failedStage = job.failed_stage ? getStageLabel(job.failed_stage) : "当前阶段";
    jobAttemptStatus.textContent = job.status === "cancelled"
      ? "任务已取消，可从最近完成阶段继续。"
      : `${failedStage}执行失败；已保留此前阶段结果。`;
  }
  renderStageHistory(job.stage_history || []);
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
  if (!window.ReadableStream || !window.ProgressStream) return pollRunStatusFallback(runId, startedAt);
  progressStreamController?.abort();
  const controller = new AbortController();
  progressStreamController = controller;
  let idleTimer;
  const resetIdle = () => {
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => controller.abort(), 25000);
  };
  let reader;
  try {
    resetIdle();
    const response = await fetch(`/api/v1/tailor-runs/${runId}/events`, {
      headers: runRequestHeaders(false), signal: controller.signal,
    });
    if (!response.ok || !response.body || !response.headers.get("content-type")?.includes("text/event-stream")) {
      throw new Error("进度连接不可用。");
    }
    let result = null;
    let terminalError = null;
    const parse = ProgressStream.parser(({event, data}) => {
      if (event !== "status") return;
      if (runId !== currentRunId) throw new Error("任务已切换或删除。");
      const job = JSON.parse(data);
      applyJobStatus(job);
      if (job.status === "completed") result = job.result;
      if (["failed", "cancelled"].includes(job.status)) {
        terminalError = new Error(job.error_message || (job.status === "cancelled" ? "任务已取消。" : "任务执行失败。"));
        terminalError.recoverable = true;
      }
    });
    reader = response.body.getReader();
    const decoder = new TextDecoder();
    while (true) {
      const {value, done} = await reader.read();
      if (runId !== currentRunId) throw new Error("任务已切换或删除。");
      if (done) break;
      resetIdle();
      parse(decoder.decode(value, {stream: true}));
      if (terminalError) throw terminalError;
      if (result) {
        cancelRunButton.classList.add("hidden");
        retryRunButton.classList.add("hidden");
        return result;
      }
      if (Date.now() - startedAt > 5 * 60 * 1000) throw new Error("等待时间过长。");
    }
    throw new Error("进度连接已关闭。");
  } catch (error) {
    if (error.recoverable || runId !== currentRunId) throw error;
    return pollRunStatusFallback(runId, startedAt);
  } finally {
    clearTimeout(idleTimer);
    controller.abort();
    if (reader) { try { await reader.cancel(); } catch (_) {} }
    if (progressStreamController === controller) progressStreamController = null;
  }
}

async function pollRunStatusFallback(runId, startedAt = Date.now()) {
  if (runId !== currentRunId) throw new Error("任务已切换或删除。");
  const response = await fetch(`/api/v1/tailor-runs/${runId}/status`, {
    headers: runRequestHeaders(false),
  });
  const job = await response.json();
  if (runId !== currentRunId) throw new Error("任务已切换或删除。");
  if (!response.ok) {
    throw new Error(job.detail || "任务状态获取失败。");
  }

  applyJobStatus(job);

  if (job.status === "completed") {
    cancelRunButton.classList.add("hidden");
    retryRunButton.classList.add("hidden");
    return job.result;
  }
  if (job.status === "failed" || job.status === "cancelled") {
    const error = new Error(job.error_message || (job.status === "cancelled" ? "任务已取消。" : "任务执行失败。"));
    error.recoverable = true;
    throw error;
  }
  if (Date.now() - startedAt > 5 * 60 * 1000) {
    throw new Error("等待时间过长，请稍后刷新页面查看结果。");
  }

  return new Promise((resolve, reject) => {
    pollTimer = window.setTimeout(() => {
      pollRunStatusFallback(runId, startedAt).then(resolve).catch(reject);
    }, 900);
  });
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (runIsBusy || draftMutationInProgress || draftIsDirty) {
    setStatus("请先完成当前任务并保存编辑，再准备新的任务。", "error");
    return;
  }
  const fileInput = document.getElementById("resume-file");
  if (!selectedArchive && (!fileInput.files || !fileInput.files[0])) {
    setStatus("请先选择简历文件。", "error");
    return;
  }

  if (!document.getElementById("jd-text").value.trim()) {
    setStatus("请先粘贴目标 JD。", "error");
    return;
  }

  if (!privacyConsent.checked) {
    setStatus("请先阅读并同意隐私与数据说明。", "error");
    return;
  }

  if (!selectedArchive && fileInput.files[0].size > currentMaxUploadBytes) {
    const maxMb = Math.max(1, Math.floor(currentMaxUploadBytes / (1024 * 1024)));
    setStatus(`简历文件不能超过 ${maxMb} MB。`, "error");
    return;
  }

  const formData = new FormData();
  if (!selectedArchive) formData.append("resume_file", fileInput.files[0]);
  formData.append("candidate_notes", document.getElementById("candidate-notes").value);
  formData.append("jd_text", document.getElementById("jd-text").value);

  submitButton.disabled = true;
  runIsBusy = true;
  syncArchiveControls();
  setStatus("正在读取简历并整理内容，请稍候。", "loading");
  confirmationPanel.classList.add("hidden");
  resultRoot.classList.add("hidden");
  resultPlaceholder.classList.remove("hidden");

  try {
    const archive = selectedArchive;
    const response = await fetch(archive ? `/api/v1/candidate-profiles/${archive.id}/preview` : "/api/v1/resume/parse-upload", {
      method: "POST",
      headers: archive ? archiveRequestHeaders() : {},
      body: archive ? JSON.stringify({
        jd_text: document.getElementById("jd-text").value,
        expected_revision: archive.revision, preferences: readPreferences(),
      }) : formData,
    });
    if (!response.ok) {
      throw new Error(await getResponseError(response, "资料准备失败，请稍后重试。"));
    }
    const payload = await response.json();
    editingArchiveId = archive?.id || "";
    document.getElementById("archive-label").value = archive?.label || "基础档案";
    archiveStorageConsent.checked = false;
    renderConfirmation(payload);
    setStatus("解析完成。请核对是否有遗漏或识别错误，采用这些资料即可继续生成。", "success");
  } catch (error) {
    setStatus(error.message || "解析失败，请检查文件格式或后端配置。", "error");
  } finally {
    submitButton.disabled = false;
    runIsBusy = false;
    syncArchiveControls();
  }
});

addFactButton.addEventListener("click", () => {
  previewData.fact_cards = collectFactCards();
  previewData.fact_cards.push({
    id: `fact_user_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`,
    category: "general",
    text: "",
    source_type: "user",
    source_span: "user_added",
    source_excerpt: "",
    evidence_level: "user_confirmed",
    confidence: 1,
    confirmed: false,
    allowed_operations: ["rewrite", "reorder", "highlight"],
  });
  profileConfirmed.checked = false;
  renderFactCards();
  Array.from(factCardList.querySelectorAll(".fact-review-card textarea")).at(-1)?.focus();
});

profileConfirmed.addEventListener("change", updateConfirmationState);

document.querySelectorAll("#confirmation-panel .profile-review-block input, #candidate-summary").forEach((input) => {
  input.addEventListener("input", () => {
    profileConfirmed.checked = false;
    updateConfirmationState();
  });
});

backToUploadButton.addEventListener("click", () => {
  previewData = null;
  confirmationPanel.classList.add("hidden");
  form.classList.remove("hidden");
  document.body.classList.remove("review-mode");
  setStatus("可以修改上传材料或候选人备注后重新解析。", "muted");
  syncArchiveControls();
});

confirmGenerateButton.addEventListener("click", async () => {
  const followUpAnswers = collectFollowUpAnswers();
  const unresolvedFollowUp = followUpAnswers.some(
    (item) => item.status === "pending" || (item.status === "answered" && !item.answer),
  );
  if (unresolvedFollowUp) {
    setStatus("请填写已选择补充的内容，或选择“本次不补充”。", "error");
    return;
  }

  const confirmedFacts = [...collectFactCards(), ...buildFactsFromFollowUpAnswers()];
  if (!confirmedFacts.length || confirmedFacts.some((fact) => !fact.confirmed || !fact.text)) {
    setStatus("请填写或移除空白条目，并勾选采用解析资料。", "error");
    return;
  }
  if (!profileConfirmed.checked) {
    setStatus("请先核对解析结果并勾选采用这些资料。", "error");
    return;
  }
  if (!document.getElementById("jd-text").value.trim()) {
    setStatus("请返回材料页填写目标 JD；也可以先保存基础档案。", "error");
    return;
  }
  if (editingArchiveId && !archiveStorageConsent.checked) {
    setStatus("复用档案前，请同意保存这次确认的资料。", "error");
    return;
  }

  const requestPayload = {
    resume_text: previewData.resume_text,
    jd_text: document.getElementById("jd-text").value,
    candidate_notes: document.getElementById("candidate-notes").value,
    preferences: readPreferences(),
    output_language: "auto",
    max_iterations: Number(document.getElementById("max-iterations").value),
    processing_mode: "full",
    confirmed_candidate_profile: collectCandidateProfile(),
    confirmed_fact_cards: confirmedFacts,
    preanalyzed_jd_profile: previewData.jd_profile,
    target_company: document.getElementById("target-company").value.trim(),
    target_role: document.getElementById("target-role").value.trim(),
  };

  confirmGenerateButton.disabled = true;
  confirmationPanel.classList.add("hidden");
  document.body.classList.remove("review-mode");
  setStatus("已确认资料，正在创建定制任务。", "loading");
  startWaitingExperience(requestPayload.jd_text);

  try {
    let archive = null;
    if (editingArchiveId) archive = await saveConfirmedArchive(confirmedFacts);
    const response = await fetch(archive ? `/api/v1/candidate-profiles/${archive.id}/jobs` : "/api/v1/tailor-runs/confirmed-jobs", {
      method: "POST",
      headers: {
        ...(archive ? archiveRequestHeaders() : { "Content-Type": "application/json" }),
        "Idempotency-Key": createIdempotencyKey(),
      },
      body: JSON.stringify(archive ? {
        jd_text: requestPayload.jd_text,
        candidate_notes: requestPayload.candidate_notes,
        output_language: requestPayload.output_language,
        preferences: requestPayload.preferences,
        max_iterations: requestPayload.max_iterations,
        expected_revision: archive.revision,
        preanalyzed_jd_profile: requestPayload.preanalyzed_jd_profile,
        target_company: requestPayload.target_company,
        target_role: requestPayload.target_role,
      } : requestPayload),
    });
    if (!response.ok) {
      throw new Error(await getResponseError(response, "请求失败，请稍后重试。"));
    }
    const payload = await response.json();
    currentRunId = payload.run_id;
    currentRunToken = payload.access_token || "";
    currentRunExpiresAt = payload.expires_at || "";
    persistActiveRun();
    if (currentRunExpiresAt) {
      taskRetention.textContent = `本次匿名任务预计在 ${new Date(currentRunExpiresAt).toLocaleString()} 自动删除，也可现在立即删除。`;
    }
    applyJobStatus(payload);
    const result = await pollRunStatus(payload.run_id);
    renderResult(result);
    setStatus("已根据你确认的事实生成定制简历。", "success");
    stopWaitingExperience(true);
    if (archive) await refreshArchiveUsage();
  } catch (error) {
    stopWaitingExperience(false);
    if (!currentRunId && !previewData) return;
    if (!error.recoverable) {
      waitingPanel.classList.add("hidden");
      confirmationPanel.classList.remove("hidden");
    }
    setStatus(error.message || "请求失败，请检查后端配置。", "error");
    updateConfirmationState();
  }
});

undoDraftButton.addEventListener("click", () => {
  if (!undoStack.length || !currentDraft) return;
  redoStack.push(cloneDraft(currentDraft));
  currentDraft = undoStack.pop();
  currentDraft.markdown = buildDraftMarkdown(currentDraft);
  renderDraftEditor();
  markDraftDirty();
  updateDraftHistoryButtons();
});

redoDraftButton.addEventListener("click", () => {
  if (!redoStack.length || !currentDraft) return;
  undoStack.push(cloneDraft(currentDraft));
  currentDraft = redoStack.pop();
  currentDraft.markdown = buildDraftMarkdown(currentDraft);
  renderDraftEditor();
  markDraftDirty();
  updateDraftHistoryButtons();
});

saveDraftButton.addEventListener("click", () => saveCurrentDraft());

restoreVersionButton.addEventListener("click", async () => {
  const version = draftVersions.find((item) => item.id === draftVersionSelect.value);
  if (!version || !currentDraft) return;
  if (draftIsDirty || draftMutationInProgress) {
    editorSaveStatus.textContent = "请先保存当前编辑，再恢复历史版本。";
    return;
  }
  restoreVersionButton.disabled = true;
  draftMutationInProgress = true;
  try {
    const response = await fetch(`/api/v1/tailor-runs/${currentRunId}/draft-versions/${version.id}/restore`, {method: "POST", headers: runRequestHeaders(false)});
    if (!response.ok) throw new Error(await getResponseError(response, "恢复版本失败。"));
    const payload = await response.json();
    undoStack.push(cloneDraft(currentDraft));
    redoStack = [];
    applyReviewedVersion(payload.version, payload.versions);
    editorSaveStatus.textContent = `已恢复“${version.label}”，刷新页面后仍使用此版本。`;
    updateDraftHistoryButtons();
  } catch (error) { editorSaveStatus.textContent = error.message; }
  finally { restoreVersionButton.disabled = false; draftMutationInProgress = false; }
});

refreshDiffButton.addEventListener("click", loadDraftDiff);
refreshScoreButton.addEventListener("click", loadScoreExplanation);
copyPlainButton.addEventListener("click", () => {
  if (currentDraft) copyText(buildDraftPlainText(currentDraft), "已复制纯文本简历。");
});
copyMarkdownButton.addEventListener("click", () => {
  if (currentDraft) copyText(buildExportMarkdown(currentDraft), "已复制 Markdown 简历。");
});
previewExportButton.addEventListener("click", previewResumeExport);
exportDocxButton.addEventListener("click", () => downloadResumeExport("docx", exportDocxButton));
exportPdfButton.addEventListener("click", () => downloadResumeExport("pdf", exportPdfButton));
exportFilename.addEventListener("blur", () => {
  exportFilename.value = sanitizeExportFilename(exportFilename.value);
});

deleteRunButton.addEventListener("click", async () => {
  if (!currentRunId || !currentRunToken) return;
  if (draftMutationInProgress) {
    setStatus("请等待当前版本操作完成，再删除任务。", "error");
    return;
  }
  if (!window.confirm("删除后无法恢复本次任务、结果和历史版本。确定立即删除吗？")) return;
  deleteRunButton.disabled = true;
  try {
    const response = await fetch(`/api/v1/tailor-runs/${currentRunId}`, {
      method: "DELETE",
      headers: runRequestHeaders(false),
    });
    if (!response.ok) throw new Error(await getResponseError(response, "任务删除失败。"));
    window.forgetHistoryRun?.(currentRunId);
    if (exportPreviewUrl) URL.revokeObjectURL(exportPreviewUrl);
    previewData = null;
    currentRunId = "";
    currentRunToken = "";
    currentRunExpiresAt = "";
    clearActiveRun();
    stopWaitingExperience(false);
    waitingPanel.classList.add("hidden");
    confirmationPanel.classList.add("hidden");
    document.body.classList.remove("review-mode");
    form.classList.remove("hidden");
    currentDraft = null;
    draftVersions = [];
    undoStack = [];
    redoStack = [];
    resultRoot.classList.add("hidden");
    resultPlaceholder.classList.remove("hidden");
    resultPlaceholder.textContent = "本次任务数据已删除，无法再通过原任务链接访问。";
    form.reset();
    setStatus("本次任务及其结果已永久删除。", "success");
  } catch (error) {
    setStatus(error.message || "任务删除失败，请稍后重试。", "error");
  } finally {
    deleteRunButton.disabled = false;
  }
});

cancelRunButton.addEventListener("click", async () => {
  if (!currentRunId || !currentRunToken) return;
  cancelRunButton.disabled = true;
  try {
    const response = await fetch(`/api/v1/tailor-runs/${currentRunId}/cancel`, {
      method: "POST",
      headers: runRequestHeaders(false),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "取消任务失败。");
    stopWaitingExperience(false);
    applyJobStatus(payload);
    setStatus("任务已取消，已完成阶段的进度仍然保留。", "muted");
  } catch (error) {
    setStatus(error.message || "取消任务失败。", "error");
  } finally {
    cancelRunButton.disabled = false;
  }
});

retryRunButton.addEventListener("click", async () => {
  if (!currentRunId || !currentRunToken) return;
  retryRunButton.disabled = true;
  try {
    const response = await fetch(`/api/v1/tailor-runs/${currentRunId}/retry`, {
      method: "POST",
      headers: runRequestHeaders(false),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "任务重试失败。");
    applyJobStatus(payload);
    setStatus("任务已重新排队，将从最近失败阶段继续。", "loading");
    const result = await pollRunStatus(currentRunId);
    renderResult(result);
    setStatus("任务恢复成功，定制简历已生成。", "success");
    stopWaitingExperience(true);
  } catch (error) {
    if (!error.recoverable) setStatus(error.message || "任务重试失败。", "error");
  } finally {
    retryRunButton.disabled = false;
  }
});
window.addEventListener("beforeunload", () => {
  if (exportPreviewUrl) URL.revokeObjectURL(exportPreviewUrl);
});

tipPrev.addEventListener("click", showPreviousTip);
tipNext.addEventListener("click", showNextTip);
loadPrivacySummary();

async function resumeSavedRun() {
  let saved;
  try {
    const params = new URLSearchParams(window.location.search);
    const linkedRun = params.get("run");
    const linkedProfile = params.get("profile");
    if (linkedRun && linkedProfile) {
      const credentials = JSON.parse(localStorage.getItem("noworrycv-candidate-archives") || "[]");
      const credential = credentials.find((item) => item.id === linkedProfile);
      if (!credential) throw new Error("请在当前浏览器连接该基础档案后再编辑插件简历。");
      const response = await fetch(`/api/v1/tailor-runs/${encodeURIComponent(linkedRun)}/status`, {
        headers: { "X-Run-Token": credential.token },
      });
      if (!response.ok) throw new Error("此生成任务已过期或不可访问；已确认简历仍可在插件下载。");
      const job = await response.json();
      sessionStorage.setItem("noworrycv-active-run", JSON.stringify({
        runId: linkedRun, token: credential.token, expiresAt: job.expires_at,
      }));
      history.replaceState(null, "", window.location.pathname);
    }
    saved = JSON.parse(sessionStorage.getItem("noworrycv-active-run") || "null");
  } catch (error) {
    clearActiveRun();
    setStatus(error.message || "无法恢复任务。", "error");
    return;
  }
  if (!saved?.runId || !saved?.token) return;
  if (saved.expiresAt && new Date(saved.expiresAt).getTime() <= Date.now()) {
    clearActiveRun();
    return;
  }
  currentRunId = saved.runId;
  currentRunToken = saved.token;
  currentRunExpiresAt = saved.expiresAt || "";
  startWaitingExperience("");
  form.classList.add("hidden");
  setStatus("正在恢复上次任务进度。", "loading");
  try {
    const result = await pollRunStatus(currentRunId);
    renderResult(result);
    setStatus("已恢复上次任务结果。", "success");
    stopWaitingExperience(true);
  } catch (error) {
    if (!error.recoverable) {
      clearActiveRun();
      currentRunId = "";
      currentRunToken = "";
      waitingPanel.classList.add("hidden");
      form.classList.remove("hidden");
      setStatus("上次任务已过期或不存在，可以重新上传。", "muted");
    } else {
      setStatus(error.message || "上次任务需要重试。", "error");
    }
  }
}

function archiveRequestHeaders(json = true) {
  const credential = archiveCredentials.find((item) => item.id === (editingArchiveId || archiveSelect.value));
  const headers = json ? { "Content-Type": "application/json" } : {};
  if (credential) headers["X-Profile-Token"] = credential.token;
  return headers;
}

function persistArchiveCredentials() {
  localStorage.setItem("noworrycv-candidate-archives", JSON.stringify(archiveCredentials));
}

function renderArchiveOptions(selectedId = archiveSelect.value) {
  archiveSelect.replaceChildren();
  const upload = document.createElement("option");
  upload.value = "";
  upload.textContent = "上传新的简历";
  archiveSelect.appendChild(upload);
  archiveCredentials.forEach((credential) => {
    const option = document.createElement("option");
    option.value = credential.id;
    option.textContent = credential.label;
    archiveSelect.appendChild(option);
  });
  archiveSelect.value = selectedId;
}

function syncArchiveControls() {
  const hasArchive = Boolean(selectedArchive && archiveSelect.value);
  editArchiveButton.disabled = !hasArchive || archiveSaving || runIsBusy;
  newArchiveJobButton.disabled = !hasArchive || archiveSaving || runIsBusy;
  exportArchiveButton.disabled = !hasArchive || archiveSaving;
  document.getElementById("save-preferences").disabled = !hasArchive || archiveSaving || runIsBusy;
  deleteArchiveButton.disabled = !hasArchive || archiveSaving || runIsBusy;
  archiveSelect.disabled = archiveSaving || runIsBusy;
  document.getElementById("resume-file").required = !hasArchive;
  document.getElementById("resume-file-field").classList.toggle("hidden", hasArchive);
  submitButton.textContent = hasArchive ? "复用档案并确认目标 JD" : "解析简历并确认";
  document.getElementById("archive-status").textContent = hasArchive
    ? `${selectedArchive.label} · 资料版本 ${selectedArchive.revision} · ${selectedArchive.fact_cards.length} 条已确认事实`
    : "上传并确认资料后，可保存为基础档案。";
}

async function refreshArchiveUsage() {
  const list = document.getElementById("archive-usage");
  list.replaceChildren();
  if (!selectedArchive) return;
  let response;
  try {
    response = await fetch(`/api/v1/candidate-profiles/${selectedArchive.id}/usage`, { headers: archiveRequestHeaders(false) });
  } catch (_error) {
    document.getElementById("archive-status").textContent += "；版本引用暂时无法载入。";
    return;
  }
  if (!response.ok) return;
  const usage = await response.json();
  usage.runs.forEach((run) => {
    const li = document.createElement("li");
    li.classList.toggle("affected", run.affected);
    const state = { completed: "已完成", failed: "失败", queued: "排队", running: "运行中", cancelled: "已取消" };
    li.textContent = `${run.job_title || "定制任务"} · ${state[run.status] || run.status} · 资料版本 ${run.profile_revision}${run.affected ? "：基础资料已更新，建议复核或重新生成；原版本保留生成时的事实。" : "：使用当前资料。"}`;
    list.appendChild(li);
  });
}

async function loadSelectedArchive() {
  const archiveId = archiveSelect.value;
  editingArchiveId = "";
  selectedArchive = null;
  syncArchiveControls();
  if (!archiveId) {
    await setPreferences();
    document.getElementById("archive-usage").replaceChildren();
    return;
  }
  const response = await fetch(`/api/v1/candidate-profiles/${archiveId}`, { headers: archiveRequestHeaders(false) });
  if (!response.ok) throw new Error(await getResponseError(response, "无法载入基础档案。"));
  const archive = await response.json();
  if (archiveSelect.value !== archiveId) return;
  selectedArchive = archive;
  await setPreferences(archive.preferences);
  document.getElementById("preferences-status").textContent = "已恢复当前档案的常用偏好，本次可继续调整。";
  syncArchiveControls();
  await refreshArchiveUsage();
}

async function saveConfirmedArchive(confirmedFacts = null) {
  if (!profileConfirmed.checked || !archiveStorageConsent.checked) throw new Error("请勾选采用这些资料，并同意保存基础档案。");
  // Ensure the browser can retain the only credential before creating the archive.
  try {
    localStorage.setItem("noworrycv-storage-check", "ok");
    localStorage.removeItem("noworrycv-storage-check");
  } catch (_error) {
    throw new Error("当前浏览器无法保存档案访问凭据，请启用本站的本地存储后再试。");
  }
  archiveSaving = true;
  updateConfirmationState();
  syncArchiveControls();
  try {
    const archiveId = editingArchiveId;
    const payload = {
      label: document.getElementById("archive-label").value.trim(),
      candidate_profile: collectCandidateProfile(),
      fact_cards: confirmedFacts || [...collectFactCards(), ...buildFactsFromFollowUpAnswers()],
      confirmed: true,
      storage_consent: true,
      expected_revision: archiveId ? selectedArchive.revision : null,
    };
    const response = await fetch(`/api/v1/candidate-profiles${archiveId ? `/${archiveId}` : ""}`, {
      method: archiveId ? "PUT" : "POST",
      headers: archiveRequestHeaders(), body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(await getResponseError(response, "基础档案保存失败。"));
    const archive = await response.json();
    const previous = archiveCredentials.find((item) => item.id === archive.id);
    archiveCredentials = archiveCredentials.filter((item) => item.id !== archive.id);
    archiveCredentials.push({ id: archive.id, token: archive.access_token || previous.token, label: archive.label });
    persistArchiveCredentials();
    selectedArchive = archive;
    editingArchiveId = archive.id;
    renderArchiveOptions(archive.id);
    // Merge confirmed answers into cards so a second save cannot add them twice.
    previewData.candidate_profile = archive.candidate_profile;
    previewData.fact_cards = archive.fact_cards;
    renderFollowUpQuestions([]);
    renderStructuredProfile(archive.candidate_profile);
    renderFactCards();
    archiveSaveStatus.textContent = `已保存「${archive.label}」，资料版本 ${archive.revision}。后续可直接复用。`;
    await refreshArchiveUsage();
    return archive;
  } finally {
    archiveSaving = false;
    syncArchiveControls();
    updateConfirmationState();
  }
}

archiveStorageConsent.addEventListener("change", updateConfirmationState);
saveArchiveButton.addEventListener("click", async () => {
  try { await saveConfirmedArchive(); }
  catch (error) { archiveSaveStatus.textContent = error.message; }
});

archiveSelect.addEventListener("change", async () => {
  if (runIsBusy || draftMutationInProgress || draftIsDirty) {
    archiveSelect.value = selectedArchive?.id || "";
    setStatus("请先等待当前任务结束，并保存编辑内容，再切换基础资料。", "error");
    return;
  }
  try {
    await loadSelectedArchive();
    previewData = null;
    confirmationPanel.classList.add("hidden");
    form.classList.remove("hidden");
    document.body.classList.remove("review-mode");
  } catch (error) { setStatus(error.message, "error"); }
});

editArchiveButton.addEventListener("click", async () => {
  if (runIsBusy || draftMutationInProgress || draftIsDirty) {
    setStatus("请先等待当前任务结束，并保存编辑内容，再维护基础档案。", "error");
    return;
  }
  try {
    await loadSelectedArchive();
    editingArchiveId = selectedArchive.id;
    document.getElementById("archive-label").value = selectedArchive.label;
    archiveStorageConsent.checked = false;
    renderConfirmation({ candidate_profile: selectedArchive.candidate_profile,
      fact_cards: selectedArchive.fact_cards, resume_text: "", follow_up_questions: [] });
    setStatus("维护基础资料后请重新确认并保存；已有简历保留原事实快照。", "muted");
  } catch (error) { setStatus(error.message, "error"); }
});

newArchiveJobButton.addEventListener("click", async () => {
  if (runIsBusy || draftMutationInProgress || draftIsDirty) {
    setStatus("请先等待当前任务结束，并保存编辑内容，再创建新任务。", "error");
    return;
  }
  try {
    await loadSelectedArchive();
    previewData = null;
    confirmationPanel.classList.add("hidden");
    form.classList.remove("hidden");
    waitingPanel.classList.add("hidden");
    document.body.classList.remove("review-mode");
    document.getElementById("jd-text").value = "";
    document.getElementById("target-company").value = "";
    document.getElementById("target-role").value = "";
    document.getElementById("jd-text").focus();
    setStatus("基础档案已就绪，填写新的 JD 后即可复用。", "muted");
  } catch (error) { setStatus(error.message, "error"); }
});

exportArchiveButton.addEventListener("click", async () => {
  exportArchiveButton.disabled = true;
  try {
    const response = await fetch(`/api/v1/candidate-profiles/${selectedArchive.id}/export`, { headers: archiveRequestHeaders(false) });
    if (!response.ok) throw new Error(await getResponseError(response, "档案导出失败。"));
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = "candidate-profile.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { setStatus(error.message, "error"); }
  finally { syncArchiveControls(); }
});

deleteArchiveButton.addEventListener("click", async () => {
  if (!selectedArchive || archiveSaving) return;
  if (!window.confirm("删除基础档案后不能再复用；已生成的任务保留各自快照，仍可在任务页单独删除。确定删除吗？")) return;
  deleteArchiveButton.disabled = true;
  try {
    const archiveId = selectedArchive.id;
    const response = await fetch(`/api/v1/candidate-profiles/${archiveId}`, { method: "DELETE", headers: archiveRequestHeaders(false) });
    if (!response.ok) throw new Error(await getResponseError(response, "档案删除失败。"));
    archiveCredentials = archiveCredentials.filter((item) => item.id !== archiveId);
    persistArchiveCredentials();
    selectedArchive = null;
    editingArchiveId = "";
    renderArchiveOptions("");
    syncArchiveControls();
    document.getElementById("archive-usage").replaceChildren();
    confirmationPanel.classList.add("hidden");
    document.body.classList.remove("review-mode");
    form.classList.remove("hidden");
    setStatus("基础档案已删除，已有任务可在结果页单独删除。", "success");
  } catch (error) { setStatus(error.message, "error"); }
  finally { syncArchiveControls(); }
});

async function initializeArchives() {
  try {
    const saved = JSON.parse(localStorage.getItem("noworrycv-candidate-archives") || "[]");
    archiveCredentials = Array.isArray(saved) ? saved.filter((item) => item.id && item.token && item.label) : [];
    renderArchiveOptions(archiveCredentials[0]?.id || "");
    await loadSelectedArchive();
  } catch (error) {
    document.getElementById("archive-status").textContent = error.message || "当前浏览器无法载入基础档案。";
  }
  window.refreshRunHistory?.();
}

initializeArchives();
resumeSavedRun();
