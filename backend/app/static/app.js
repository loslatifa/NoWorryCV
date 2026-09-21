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
const confirmAllButton = document.getElementById("confirm-all-button");
const profileConfirmed = document.getElementById("profile-confirmed");
const backToUploadButton = document.getElementById("back-to-upload-button");
const confirmGenerateButton = document.getElementById("confirm-generate-button");

let previewData = null;
let currentRunId = "";
let currentDraft = null;
let draftVersions = [];
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
let scoreExplanation = null;
let scoreExplanationIsStale = false;

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
  if (!items?.length) return;
  const group = document.createElement("section");
  group.className = "structured-group";
  const heading = document.createElement("h5");
  heading.textContent = title;
  group.appendChild(heading);

  items.forEach((item, index) => {
    const entry = document.createElement("div");
    entry.className = "structured-entry";
    entry.dataset.kind = kind;
    entry.dataset.index = String(index);
    fields.forEach(([label, fieldName]) => {
      entry.appendChild(makeReviewField(label, item[fieldName], fieldName));
    });
    group.appendChild(entry);
  });
  structuredProfile.appendChild(group);
}

function renderStructuredProfile(profile) {
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
    empty.textContent = "未解析到结构化经历；你仍可通过下方事实卡补充信息。";
    structuredProfile.appendChild(empty);
  }
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
  });
  return profile;
}

function factCategoryLabel(category) {
  const labels = {
    work_bullet: "工作事实",
    project_bullet: "项目事实",
    skill: "技能",
    education: "教育",
    certification: "证书",
    achievement: "补充成果",
    general: "补充事实",
  };
  return labels[category] || category || "事实";
}

function collectFactCards() {
  return Array.from(factCardList.querySelectorAll(".fact-review-card")).map((cardElement) => {
    const original = previewData.fact_cards.find((card) => card.id === cardElement.dataset.factId) || {};
    return {
      ...original,
      id: cardElement.dataset.factId,
      category: cardElement.querySelector("select").value,
      text: cardElement.querySelector("textarea").value.trim(),
      confirmed: cardElement.querySelector("input[type='checkbox']").checked,
    };
  });
}

function collectFollowUpAnswers() {
  return Array.from(followUpList.querySelectorAll(".follow-up-card")).map((card) => ({
    id: card.dataset.questionId,
    status: card.querySelector("select").value,
    answer: card.querySelector("textarea").value.trim(),
    suggestedCategory: card.dataset.suggestedCategory || "general",
    prompt: card.dataset.prompt || "",
  }));
}

function renderFollowUpQuestions(questions) {
  followUpList.innerHTML = "";
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
    priority.className = `question-priority ${question.priority === "recommended" ? "recommended" : ""}`;
    priority.textContent = question.priority === "recommended" ? "建议回答" : "选答";
    const status = document.createElement("select");
    [
      ["pending", "请选择处理方式"],
      ["answered", "回答并加入事实"],
      ["unavailable", "无法提供"],
      ["skipped", "暂时跳过"],
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
    answer.placeholder = "请写成你能够在面试中解释和证明的完整事实。";
    answer.setAttribute("aria-label", "补充事实回答");

    status.addEventListener("change", () => {
      answer.classList.toggle("hidden", status.value !== "answered");
      updateConfirmationState();
    });
    answer.addEventListener("input", updateConfirmationState);
    article.append(header, prompt, reason, answer);
    followUpList.appendChild(article);
  });
}

function buildFactsFromFollowUpAnswers() {
  return collectFollowUpAnswers()
    .filter((item) => item.status === "answered" && item.answer)
    .map((item) => ({
      id: `fact_follow_up_${item.id}`,
      category: item.suggestedCategory,
      text: item.answer,
      source_type: "user",
      source_span: `follow_up.${item.id}`,
      source_excerpt: item.prompt,
      evidence_level: "user_confirmed",
      confidence: 1,
      confirmed: true,
      allowed_operations: ["rewrite", "reorder", "highlight"],
    }));
}

function updateConfirmationState() {
  const checkboxes = Array.from(factCardList.querySelectorAll("input[type='checkbox']"));
  const confirmedCount = checkboxes.filter((checkbox) => checkbox.checked).length;
  confirmationProgress.textContent = `${confirmedCount} / ${checkboxes.length} 已确认`;
  const allFactsReady = checkboxes.length > 0 && checkboxes.every((checkbox) => checkbox.checked);
  const allTextsReady = Array.from(factCardList.querySelectorAll("textarea")).every(
    (textarea) => textarea.value.trim().length > 0,
  );
  const followUps = collectFollowUpAnswers();
  const resolvedFollowUps = followUps.filter(
    (item) => item.status !== "pending" && (item.status !== "answered" || item.answer),
  );
  followUpProgress.textContent = `${resolvedFollowUps.length} / ${followUps.length} 已处理`;
  const allFollowUpsReady = resolvedFollowUps.length === followUps.length;
  confirmGenerateButton.disabled = !(
    allFactsReady &&
    allTextsReady &&
    allFollowUpsReady &&
    profileConfirmed.checked
  );
}

function renderFactCards() {
  factCardList.innerHTML = "";
  previewData.fact_cards.forEach((fact) => {
    const article = document.createElement("article");
    article.className = `fact-review-card${fact.confidence < 0.8 ? " low-confidence" : ""}`;
    article.dataset.factId = fact.id;

    const header = document.createElement("div");
    header.className = "fact-card-head";
    const category = document.createElement("select");
    ["work_bullet", "project_bullet", "skill", "education", "certification", "achievement", "general"].forEach(
      (value) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = factCategoryLabel(value);
        option.selected = value === fact.category;
        category.appendChild(option);
      },
    );

    const confidence = document.createElement("span");
    confidence.className = "confidence-badge";
    confidence.textContent = fact.source_type === "user" ? "用户补充" : `置信度 ${Math.round(fact.confidence * 100)}%`;
    header.append(category, confidence);

    const textarea = document.createElement("textarea");
    textarea.rows = 3;
    textarea.value = fact.text;
    textarea.setAttribute("aria-label", "事实内容");

    const source = document.createElement("p");
    source.className = "fact-source";
    source.textContent = fact.source_excerpt
      ? `原始内容：${fact.source_excerpt}`
      : fact.source_span
        ? `来源位置：${fact.source_span}`
        : "来源：用户补充";

    const footer = document.createElement("div");
    footer.className = "fact-card-footer";
    const confirmLabel = document.createElement("label");
    confirmLabel.className = "fact-confirm";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = Boolean(fact.confirmed);
    const confirmText = document.createElement("span");
    confirmText.textContent = "此事实准确";
    confirmLabel.append(checkbox, confirmText);

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "text-button danger-button";
    deleteButton.textContent = "删除";
    deleteButton.addEventListener("click", () => {
      previewData.fact_cards = collectFactCards().filter((item) => item.id !== fact.id);
      renderFactCards();
    });

    textarea.addEventListener("input", () => {
      checkbox.checked = false;
      updateConfirmationState();
    });
    category.addEventListener("change", () => {
      checkbox.checked = false;
      updateConfirmationState();
    });
    checkbox.addEventListener("change", updateConfirmationState);
    footer.append(confirmLabel, deleteButton);
    article.append(header, textarea, source, footer);
    factCardList.appendChild(article);
  });
  updateConfirmationState();
}

function renderConfirmation(payload) {
  previewData = payload;
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

function invalidateExportPreview() {
  if (!exportPreviewSnapshot) return;
  exportPreviewSnapshot = "";
  exportDocxButton.disabled = true;
  exportPdfButton.disabled = true;
  exportOverflowWarning.classList.add("hidden");
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
  const snapshot = draftSnapshot();
  try {
    const response = await fetch(`/api/v1/tailor-runs/${currentRunId}/export-preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ draft: currentDraft, filename: sanitizeExportFilename(exportFilename.value) }),
    });
    if (!response.ok) throw new Error(await getResponseError(response, "分页预览生成失败。"));
    const blob = await response.blob();
    if (snapshot !== draftSnapshot()) {
      exportStatus.textContent = "简历内容已变化，请重新生成分页预览。";
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
    exportStatus.textContent = overflow
      ? `预览共 ${pageCount} 页，可以导出，但不符合单页模板目标。`
      : "预览为 1 页，适合按单页 ATS 简历导出。";
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
  if (!exportPreviewSnapshot || exportPreviewSnapshot !== draftSnapshot()) {
    exportStatus.textContent = "请先为当前内容生成分页预览。";
    return;
  }
  button.disabled = true;
  exportStatus.textContent = `正在生成 ${format.toUpperCase()}…`;
  const filename = sanitizeExportFilename(exportFilename.value);
  const requestedSnapshot = draftSnapshot();
  try {
    const response = await fetch(`/api/v1/tailor-runs/${currentRunId}/export/${format}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ draft: currentDraft, filename }),
    });
    if (!response.ok) throw new Error(await getResponseError(response, "导出失败。"));
    const blob = await response.blob();
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
    button.disabled = !exportPreviewSnapshot || exportPreviewSnapshot !== draftSnapshot() || requestedSnapshot !== draftSnapshot();
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
  const requestedSnapshot = draftSnapshot();
  refreshScoreButton.disabled = true;
  scoreStatus.textContent = "正在计算原始简历与当前版本的分项对照…";
  scoreStatus.classList.remove("is-stale");
  try {
    const response = await fetch(`/api/v1/tailor-runs/${currentRunId}/score`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ draft: currentDraft }),
    });
    const payload = await response.json();
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
    document.getElementById("risk-level").textContent = payload.compliance_report.risk_level;
    scoreStatus.textContent = draftIsDirty
      ? "已按当前未保存内容计算；保存后会写入版本记录。"
      : "已按当前版本计算。";
  } catch (error) {
    scoreStatus.textContent = error.message || "评分计算失败。";
  } finally {
    refreshScoreButton.disabled = false;
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
    state.textContent = decision === "accepted" ? "已接受" : "已拒绝";
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
    accept.className = `diff-decision${decision === "accepted" ? " is-selected" : ""}`;
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
  const before = cloneDraft(currentDraft);
  diffDecisions[itemId] = decision;
  const next = rebuildDraftFromDiffDecisions();
  if (draftSnapshot(before) !== draftSnapshot(next)) {
    undoStack.push(before);
    redoStack = [];
  }
  currentDraft = next;
  renderDraftEditor();
  markDraftDirty(false);
  renderDraftDiff();
  updateDiffSummary();
  updateDraftHistoryButtons();
}

async function loadDraftDiff() {
  if (!currentRunId || !currentDraft) return;
  refreshDiffButton.disabled = true;
  diffSummary.textContent = "正在生成逐条差异…";
  try {
    const response = await fetch(`/api/v1/tailor-runs/${currentRunId}/draft-diff`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ draft: currentDraft }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "差异生成失败。");
    draftDiff = payload;
    diffBaseDraft = cloneDraft(currentDraft);
    diffDecisions = Object.fromEntries(payload.items.map((item) => [item.id, "accepted"]));
    draftDiffIsStale = false;
    updateDiffSummary();
    renderDraftDiff();
  } catch (error) {
    draftDiff = null;
    draftDiffIsStale = false;
    diffSummary.textContent = error.message || "差异生成失败。";
    draftDiffList.innerHTML = "";
  } finally {
    refreshDiffButton.disabled = false;
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
    option.textContent = `${version.label}${time ? ` · ${time}` : ""}`;
    draftVersionSelect.appendChild(option);
  });
}

function applyReviewedVersion(version, versions) {
  currentDraft = cloneDraft(version.draft);
  draftVersions = versions || draftVersions;
  draftIsDirty = false;
  renderDraftEditor();
  renderVersionOptions();
  const risk = version.compliance_report?.risk_level || "low";
  editorRiskBanner.textContent = `真实性风险：${risk}；JD 匹配参考分：${version.ats_report?.score ?? "-"}。`;
  editorRiskBanner.className = `editor-risk-banner ${risk}`;
  editorSaveStatus.textContent = version.label || "版本已保存。";
  document.getElementById("risk-level").textContent = risk;
  document.getElementById("ats-score").textContent = version.ats_report?.score ?? "-";
  resetExportPreview();
  loadDraftDiff();
  loadScoreExplanation();
}

function initializeDraftEditor(result) {
  currentRunId = result.run_id;
  currentCandidateProfile = result.candidate_profile || { basics: {} };
  currentDraft = cloneDraft(result.final_package.draft);
  draftVersions = result.draft_versions || [];
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
  const latestVersion = draftVersions[draftVersions.length - 1];
  const risk = latestVersion.compliance_report?.risk_level || "low";
  editorRiskBanner.textContent = `真实性风险：${risk}；JD 匹配参考分：${latestVersion.ats_report?.score ?? "-"}。`;
  editorRiskBanner.className = `editor-risk-banner ${risk}`;
  editorSaveStatus.textContent = latestVersion.label || "版本已保存。";
  document.getElementById("risk-level").textContent = risk;
  document.getElementById("ats-score").textContent = latestVersion.ats_report?.score ?? "-";
  const candidateName = currentCandidateProfile.basics?.name?.trim();
  exportFilename.value = candidateName ? `${candidateName}-定制简历` : "定制简历";
  resetExportPreview();
  loadDraftDiff();
  loadScoreExplanation();
}

async function saveCurrentDraft(label = "手工保存") {
  saveDraftButton.disabled = true;
  editorSaveStatus.textContent = "正在保存并重新审查…";
  try {
    const response = await fetch(`/api/v1/tailor-runs/${currentRunId}/draft`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ draft: currentDraft, label }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "保存失败。");
    applyReviewedVersion(payload.version, payload.versions);
  } catch (error) {
    editorSaveStatus.textContent = error.message || "保存失败。";
  } finally {
    saveDraftButton.disabled = false;
  }
}

async function rewriteDraftPart(targetType, sectionIndex, itemIndex, button) {
  const before = cloneDraft(currentDraft);
  button.disabled = true;
  button.textContent = "重写中…";
  editorSaveStatus.textContent = "正在局部重写并审查…";
  try {
    const response = await fetch(`/api/v1/tailor-runs/${currentRunId}/rewrite-part`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
  }
}

function renderResult(result) {
  document.body.classList.remove("review-mode");
  form.classList.remove("hidden");
  const latestReview = result.reviews[result.reviews.length - 1];
  document.getElementById("ats-score").textContent = latestReview?.ats_report?.score ?? "-";
  document.getElementById("risk-level").textContent = latestReview?.compliance_report?.risk_level ?? "-";
  document.getElementById("hiring-track").textContent = humanizeHiringTrack(result.jd_profile?.hiring_track);
  document.getElementById("stop-reason").textContent = result.stop_reason || "-";
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

  if (!document.getElementById("jd-text").value.trim()) {
    setStatus("请先粘贴目标 JD。", "error");
    return;
  }

  const formData = new FormData();
  formData.append("resume_file", fileInput.files[0]);
  formData.append("candidate_notes", document.getElementById("candidate-notes").value);
  formData.append("jd_text", document.getElementById("jd-text").value);

  submitButton.disabled = true;
  setStatus("正在解析简历并提取可追溯事实，请稍候。", "loading");
  confirmationPanel.classList.add("hidden");
  resultRoot.classList.add("hidden");
  resultPlaceholder.classList.remove("hidden");

  try {
    const response = await fetch("/api/v1/resume/parse-upload", {
      method: "POST",
      body: formData,
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "简历解析失败，请稍后重试。");
    }
    renderConfirmation(payload);
    setStatus("解析完成。请确认基本信息、经历结构和事实卡后再开始生成。", "success");
  } catch (error) {
    setStatus(error.message || "解析失败，请检查文件格式或后端配置。", "error");
  } finally {
    submitButton.disabled = false;
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
  renderFactCards();
  factCardList.lastElementChild?.querySelector("textarea")?.focus();
});

confirmAllButton.addEventListener("click", () => {
  factCardList.querySelectorAll("input[type='checkbox']").forEach((checkbox) => {
    checkbox.checked = true;
  });
  updateConfirmationState();
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
});

confirmGenerateButton.addEventListener("click", async () => {
  const followUpAnswers = collectFollowUpAnswers();
  const unresolvedFollowUp = followUpAnswers.some(
    (item) => item.status === "pending" || (item.status === "answered" && !item.answer),
  );
  if (unresolvedFollowUp) {
    setStatus("请回答、跳过或标记无法提供每个补充问题。", "error");
    return;
  }

  const confirmedFacts = [...collectFactCards(), ...buildFactsFromFollowUpAnswers()];
  if (!confirmedFacts.length || confirmedFacts.some((fact) => !fact.confirmed || !fact.text)) {
    setStatus("请确认所有保留的事实，空白或不准确的内容可以直接删除。", "error");
    return;
  }
  if (!profileConfirmed.checked) {
    setStatus("请先确认基本信息和经历结构。", "error");
    return;
  }

  const requestPayload = {
    resume_text: previewData.resume_text,
    jd_text: document.getElementById("jd-text").value,
    candidate_notes: document.getElementById("candidate-notes").value,
    output_language: document.getElementById("output-language").value,
    max_iterations: Number(document.getElementById("max-iterations").value),
    processing_mode: "full",
    confirmed_candidate_profile: collectCandidateProfile(),
    confirmed_fact_cards: confirmedFacts,
    preanalyzed_jd_profile: previewData.jd_profile,
  };

  confirmGenerateButton.disabled = true;
  confirmationPanel.classList.add("hidden");
  document.body.classList.remove("review-mode");
  setStatus("已确认资料，正在创建定制任务。", "loading");
  startWaitingExperience(requestPayload.jd_text);

  try {
    const response = await fetch("/api/v1/tailor-runs/confirmed-jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestPayload),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "请求失败，请稍后重试。");
    }
    applyJobStatus(payload);
    const result = await pollRunStatus(payload.run_id);
    renderResult(result);
    setStatus("已根据你确认的事实生成定制简历。", "success");
    stopWaitingExperience(true);
  } catch (error) {
    stopWaitingExperience(false);
    waitingPanel.classList.add("hidden");
    confirmationPanel.classList.remove("hidden");
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

restoreVersionButton.addEventListener("click", () => {
  const version = draftVersions.find((item) => item.id === draftVersionSelect.value);
  if (!version || !currentDraft) return;
  undoStack.push(cloneDraft(currentDraft));
  redoStack = [];
  currentDraft = cloneDraft(version.draft);
  currentDraft.markdown = buildDraftMarkdown(currentDraft);
  renderDraftEditor();
  markDraftDirty();
  editorSaveStatus.textContent = `已恢复“${version.label}”，保存后将设为当前版本。`;
  updateDraftHistoryButtons();
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
window.addEventListener("beforeunload", () => {
  if (exportPreviewUrl) URL.revokeObjectURL(exportPreviewUrl);
});

tipPrev.addEventListener("click", showPreviousTip);
tipNext.addEventListener("click", showNextTip);
