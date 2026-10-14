const RESUME_STORAGE_KEY = "jobAutoAgent.resumeOverride";
const MAPPER_VERSION = "rule-mapper@0.2.0";
const PLANNER_VERSION = "form-planner@0.1.0";
const PREVIEW_VERSION = "fill-preview@0.1.0";

const REPEATABLE_CONFIGS = {
  education: {
    label: "教育经历",
    startRole: "school",
    typeTokens: ["education", "school", "university", "college", "学历", "教育", "学校", "院校", "毕业院校"],
    addTokens: ["education", "school", "学历", "教育", "学校", "院校"],
    roles: {
      school: ["school", "school name", "university", "college", "institution", "学校", "院校", "毕业院校", "大学"],
      degree: ["degree", "education level", "qualification", "学历", "学位", "最高学历"],
      major: ["major", "field of study", "specialization", "专业", "研究方向"],
      start_date: ["start", "start date", "from", "入学", "开始时间", "开始日期"],
      end_date: ["end", "end date", "to", "graduation", "graduate", "毕业", "结束时间", "结束日期"],
      gpa: ["gpa", "grade point", "绩点", "成绩", "平均分"]
    }
  },
  work_experience: {
    label: "工作经历",
    startRole: "company",
    typeTokens: ["work", "work experience", "internship", "employment", "company", "工作", "工作经历", "实习", "实习经历", "任职"],
    addTokens: ["work", "work experience", "internship", "employment", "company", "工作", "工作经历", "实习", "实习经历"],
    roles: {
      company: ["company", "company name", "employer", "organization", "公司", "公司名称", "单位"],
      title: ["title", "job title", "position", "role", "职位", "岗位", "职务"],
      start_date: ["start", "start date", "from", "入职", "开始时间", "开始日期"],
      end_date: ["end", "end date", "to", "离职", "结束时间", "结束日期"],
      description: ["description", "responsibility", "work content", "工作描述", "工作内容", "职责", "描述"],
      highlights: ["highlight", "achievement", "impact", "工作亮点", "成果", "业绩", "亮点"]
    }
  },
  projects: {
    label: "项目经历",
    startRole: "name",
    typeTokens: ["project", "portfolio", "项目", "项目经历", "项目经验"],
    addTokens: ["project", "portfolio", "项目"],
    roles: {
      name: ["project name", "name", "项目名称", "项目名"],
      role: ["project role", "role", "职责", "角色", "项目角色"],
      start_date: ["start", "start date", "from", "开始时间", "开始日期"],
      end_date: ["end", "end date", "to", "结束时间", "结束日期"],
      description: ["description", "project description", "项目描述", "项目介绍", "描述"],
      tech_stack: ["tech stack", "technology", "skills", "技术栈", "技术", "工具"],
      highlights: ["highlight", "achievement", "impact", "项目亮点", "成果", "亮点"]
    }
  }
};

const COMPLETENESS_RULES = [
  {
    section: "personal_info",
    label: "基础信息",
    fields: [
      { path: "personal_info.name", label: "姓名", severity: "critical" },
      { path: "personal_info.email", label: "邮箱", severity: "critical" },
      { path: "personal_info.phone", label: "电话", severity: "critical" },
      { path: "personal_info.location", label: "城市 / 所在地", severity: "medium" },
      { path: "personal_info.github", label: "GitHub", severity: "low" },
      { path: "personal_info.linkedin", label: "LinkedIn", severity: "low" }
    ]
  },
  {
    section: "education",
    label: "教育经历",
    minItems: 1,
    fields: [
      { path: "school", label: "学校", severity: "critical" },
      { path: "degree", label: "学历 / 学位", severity: "critical" },
      { path: "major", label: "专业", severity: "medium" },
      { path: "start_date", label: "开始时间", severity: "medium" },
      { path: "end_date", label: "结束时间", severity: "critical" },
      { path: "gpa", label: "GPA", severity: "low" }
    ]
  },
  {
    section: "work_experience",
    label: "工作经历",
    minItems: 1,
    fields: [
      { path: "company", label: "公司", severity: "critical" },
      { path: "title", label: "职位", severity: "critical" },
      { path: "start_date", label: "开始时间", severity: "medium" },
      { path: "end_date", label: "结束时间", severity: "medium" },
      { path: "description", label: "描述", severity: "critical" },
      { path: "highlights", label: "亮点 / 成果", severity: "medium" }
    ]
  },
  {
    section: "projects",
    label: "项目经历",
    minItems: 1,
    fields: [
      { path: "name", label: "项目名", severity: "critical" },
      { path: "role", label: "角色", severity: "medium" },
      { path: "start_date", label: "开始时间", severity: "low" },
      { path: "end_date", label: "结束时间", severity: "low" },
      { path: "description", label: "描述", severity: "critical" },
      { path: "tech_stack", label: "技术栈", severity: "medium" },
      { path: "highlights", label: "亮点 / 成果", severity: "medium" }
    ]
  },
  { section: "skills", label: "技能", minItems: 3, fields: [] },
  { section: "languages", label: "语言能力", minItems: 1, fields: [] },
  { section: "certifications", label: "证书", minItems: 1, severity: "low", fields: [] },
  { section: "awards", label: "获奖", minItems: 1, severity: "low", fields: [] },
  {
    section: "attachments",
    label: "附件",
    fields: [
      { path: "attachments.resume_pdf", label: "简历 PDF", severity: "medium" },
      { path: "attachments.transcript", label: "成绩单", severity: "low" },
      { path: "attachments.portfolio", label: "作品集", severity: "low" }
    ]
  }
];

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // Only our extension pages can request mappings containing candidate data.
  if (sender.url && !sender.url.startsWith(chrome.runtime.getURL(""))) return false;
  handleMessage(message)
    .then((payload) => sendResponse({ ok: true, ...payload }))
    .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
  return true;
});

async function handleMessage(message) {
  switch (message?.type) {
    case "GET_RESUME": {
      const resume = await loadResume();
      return { resume, source: await getResumeSource() };
    }
    case "SAVE_RESUME": {
      if (!message.resume || typeof message.resume !== "object") {
        throw new Error("SAVE_RESUME requires a resume object.");
      }
      await chrome.storage.local.set({ [RESUME_STORAGE_KEY]: message.resume });
      return { source: "storage" };
    }
    case "RESET_RESUME": {
      await chrome.storage.local.remove(RESUME_STORAGE_KEY);
      return { source: "packaged-default" };
    }
    case "MAP_FIELDS": {
      const resume = message.resume || await loadResume();
      const fields = Array.isArray(message.fields) ? message.fields : [];
      return {
        mapper_version: MAPPER_VERSION,
        mappings: mapFields(fields, resume)
      };
    }
    case "PLAN_FORM": {
      const resume = message.resume || await loadResume();
      const fields = Array.isArray(message.fields) ? message.fields : [];
      const buttons = Array.isArray(message.buttons) ? message.buttons : [];
      return {
        planner_version: PLANNER_VERSION,
        plan: planForm(fields, buttons, resume)
      };
    }
    case "CHECK_RESUME_COMPLETENESS": {
      const resume = message.resume || await loadResume();
      return {
        completeness: checkResumeCompleteness(resume)
      };
    }
    case "BUILD_FILL_PREVIEW": {
      const resume = message.resume || await loadResume();
      const fields = Array.isArray(message.fields) ? message.fields : [];
      return {
        preview_version: PREVIEW_VERSION,
        preview: buildFillPreview(fields, resume)
      };
    }
    default:
      throw new Error(`Unsupported message type: ${message?.type || "unknown"}`);
  }
}

async function loadResume() {
  const stored = await chrome.storage.local.get(RESUME_STORAGE_KEY);
  if (stored[RESUME_STORAGE_KEY]) {
    return stored[RESUME_STORAGE_KEY];
  }

  throw new Error("请先连接 NoWorryCV 基础档案并生成微调简历。");
}

async function getResumeSource() {
  const stored = await chrome.storage.local.get(RESUME_STORAGE_KEY);
  return stored[RESUME_STORAGE_KEY] ? "storage" : "packaged-default";
}

function mapFields(fields, resume) {
  const context = createMappingContext();
  return fields.map((field) => mapSingleField(field, resume, context));
}

function mapSingleField(field, resume, context) {
  // A nearby section or previous field must not override this field's own label.
  const directText = [field.label, field.placeholder, field.name, field.id, field.field_role].filter(Boolean).join(" ");
  const lowerText = normalize(directText);
  const repeatableType = detectRepeatableType(field, normalize(`${directText} ${field.section || ""}`));
  const repeatableRole = repeatableType ? detectRepeatableRole(repeatableType, field, lowerText) : "";

  if (repeatableType && repeatableRole) {
    const index = resolveRepeatableIndex(field, repeatableType, repeatableRole, context);
    const path = `${repeatableType}.${index}.${repeatableRole}`;
    const rawValue = getValueByPath(resume, path);
    const fillValue = formatRepeatableValue(rawValue, repeatableRole);
    const confidence = fillValue ? scoreRepeatableField(field, lowerText, repeatableType, repeatableRole) : 0.35;
    return buildMapping(field, {
      path: fillValue ? path : null,
      value: fillValue,
      confidence,
      notes: fillValue
        ? `Mapped repeatable ${repeatableType}[${index}].${repeatableRole}.`
        : `No resume value found for ${path}.`
    });
  }

  return buildMapping(field, matchStaticField(lowerText, field, resume));
}

function buildMapping(field, result) {
  return {
    selector: field.selector,
    field_selector: field.selector,
    field_label: field.label || field.placeholder || field.name || field.id || bestSemanticLabel(field) || "",
    field_type: field.type || field.tag || "text",
    matched_resume_path: result.path,
    fill_value: result.value,
    confidence: result.confidence,
    notes: result.notes,
    mapper_version: MAPPER_VERSION
  };
}

function matchStaticField(lowerText, field, resume) {
  const personal = resume.personal_info || {};
  const rules = [
    {
      path: "personal_info.email",
      value: personal.email,
      tokens: ["email", "e-mail", "mail", "email address", "邮箱", "电子邮件"],
      notes: "Rule matched email."
    },
    {
      path: "personal_info.phone",
      value: personal.phone,
      tokens: ["phone", "mobile", "mobile phone", "phone number", "tel", "telephone", "cell", "contact number", "手机", "手机号", "手机号码", "电话", "联系电话", "联系方式"],
      rejectTokens: ["country code", "area code", "区号", "国家码", "国家代码"],
      notes: "Rule matched phone."
    },
    {
      path: "personal_info.phone_country_code",
      value: extractPhoneCountryCode(personal.phone),
      tokens: ["country code", "area code", "phone code", "区号", "国家码", "国家代码"],
      notes: "Rule extracted phone country code."
    },
    {
      path: "personal_info.github",
      value: personal.github,
      tokens: ["github", "git hub", "repository", "代码仓库"],
      notes: "Rule matched GitHub profile."
    },
    {
      path: "personal_info.linkedin",
      value: personal.linkedin,
      tokens: ["linkedin", "linked in", "领英"],
      notes: "Rule matched LinkedIn profile."
    },
    {
      path: "personal_info.location",
      value: personal.location || personal.city,
      tokens: ["location", "city", "address", "current city", "所在地", "城市", "现居", "地址", "居住地"],
      notes: "Rule matched location."
    },
    {
      path: "skills",
      value: formatSkills(resume.skills),
      tokens: ["skills", "technical skills", "tech stack", "技能", "专业技能"],
      notes: "Rule matched skills."
    },
    {
      path: "summary",
      value: buildSelfIntroduction(resume),
      tokens: ["summary", "self introduction", "self evaluation", "introduction", "about yourself", "personal statement", "自我介绍", "自我评价", "个人简介", "个人陈述"],
      notes: "Rule generated a concise self introduction."
    },
    {
      path: "personal_info.name",
      value: personal.name,
      tokens: ["full name", "real name", "name", "applicant", "candidate", "user name", "姓名", "真实姓名", "申请人", "候选人姓名"],
      rejectTokens: ["company", "school", "project", "公司", "学校", "项目"],
      notes: "Rule matched candidate name."
    }
  ];

  const fieldType = normalize(field.type || "");
  if (fieldType === "email" && personal.email) {
    return exact("personal_info.email", personal.email, 0.98, "Input type indicates email.");
  }
  if ((fieldType === "tel" || fieldType === "phone") && personal.phone) {
    return exact("personal_info.phone", personal.phone, 0.98, "Input type indicates phone.");
  }
  if (fieldType === "url") {
    if (hasAny(lowerText, ["github"]) && personal.github) {
      return exact("personal_info.github", personal.github, 0.96, "URL field matched GitHub.");
    }
    if (hasAny(lowerText, ["linkedin", "linked in", "领英"]) && personal.linkedin) {
      return exact("personal_info.linkedin", personal.linkedin, 0.96, "URL field matched LinkedIn.");
    }
  }

  for (const rule of rules) {
    if (!rule.value) {
      continue;
    }
    if (rule.rejectTokens && hasAny(lowerText, rule.rejectTokens)) {
      continue;
    }
    const matchedToken = firstMatchedToken(lowerText, rule.tokens);
    if (matchedToken) {
      return exact(rule.path, rule.value, scoreByFieldEvidence(field, matchedToken), rule.notes);
    }
  }

  return {
    path: null,
    value: "",
    confidence: 0.2,
    notes: "No deterministic rule matched. Left for manual review."
  };
}

function planForm(fields, buttons, resume) {
  const mappings = mapFields(fields, resume);
  const repeatableSections = Object.keys(REPEATABLE_CONFIGS).map((type) => {
    const config = REPEATABLE_CONFIGS[type];
    const resumeCount = Array.isArray(resume[type]) ? resume[type].length : 0;
    const visibleGroupCount = estimateVisibleGroupCount(type, fields, mappings);
    const missingGroupCount = Math.max(0, resumeCount - visibleGroupCount);
    const addButton = findAddButton(type, buttons);
    const confidence = visibleGroupCount > 0 ? 0.78 : addButton ? 0.58 : 0.35;
    return {
      type,
      label: config.label,
      resume_count: resumeCount,
      visible_group_count: visibleGroupCount,
      missing_group_count: missingGroupCount,
      confidence,
      add_button_selector: addButton?.selector || null,
      add_button_label: addButton ? formatButtonLabel(addButton) : "",
      notes: buildSectionPlanNotes(config, resumeCount, visibleGroupCount, missingGroupCount, addButton)
    };
  });

  const warnings = [];
  repeatableSections.forEach((section) => {
    if (section.missing_group_count > 0 && !section.add_button_selector) {
      warnings.push(`${section.label} 需要新增 ${section.missing_group_count} 组，但没有找到安全的新增按钮，需要手动展开。`);
    }
  });

  return {
    summary: {
      visible_field_count: fields.length,
      fillable_now_count: mappings.filter((item) => item.matched_resume_path && Number(item.confidence) >= 0.6).length,
      low_confidence_count: mappings.filter((item) => Number(item.confidence) < 0.6).length
    },
    repeatable_sections: repeatableSections,
    warnings
  };
}

function buildFillPreview(fields, resume) {
  const mappings = mapFields(fields, resume);
  const items = mappings.map((mapping, index) => {
    const confidence = Number(mapping.confidence) || 0;
    const hasValue = Boolean(mapping.fill_value && mapping.matched_resume_path);
    return {
      id: `preview-${index}`,
      selector: mapping.selector,
      field_label: mapping.field_label || mapping.selector || "未命名字段",
      field_type: mapping.field_type || "text",
      matched_resume_path: mapping.matched_resume_path,
      fill_value: mapping.fill_value || "",
      confidence,
      notes: mapping.notes || "",
      enabled: hasValue && confidence >= 0.6,
      edited: false
    };
  });

  return {
    preview_id: `preview-${Date.now()}`,
    items,
    summary: {
      total: items.length,
      enabled_count: items.filter((item) => item.enabled).length,
      disabled_count: items.filter((item) => !item.enabled).length,
      low_confidence_count: items.filter((item) => item.confidence < 0.6).length
    }
  };
}

function checkResumeCompleteness(resume) {
  const sections = COMPLETENESS_RULES.map((rule) => checkCompletenessSection(resume, rule));
  const totalRequired = sections.reduce((sum, section) => sum + section.required_count, 0);
  const totalPresent = sections.reduce((sum, section) => sum + section.present_count, 0);
  const criticalMissing = sections.flatMap((section) => section.missing).filter((item) => item.severity === "critical");
  const mediumMissing = sections.flatMap((section) => section.missing).filter((item) => item.severity === "medium");
  const score = totalRequired ? Math.round((totalPresent / totalRequired) * 100) : 100;

  return {
    score,
    status: criticalMissing.length ? "blocked" : mediumMissing.length ? "needs_attention" : "ready",
    sections,
    warnings: buildCompletenessWarnings(sections, criticalMissing, mediumMissing)
  };
}

function checkCompletenessSection(resume, rule) {
  const missing = [];
  let requiredCount = 0;
  let presentCount = 0;

  if (rule.minItems) {
    requiredCount += rule.minItems;
    const items = Array.isArray(resume[rule.section]) ? resume[rule.section] : [];
    if (items.length >= rule.minItems) {
      presentCount += rule.minItems;
    } else {
      missing.push({
        path: rule.section,
        label: `${rule.label}至少 ${rule.minItems} 条`,
        severity: rule.severity || "critical",
        suggestion: `请补充 ${rule.label} 数据，真实招聘表单常会要求填写。`
      });
    }
  }

  if (isRepeatableSection(rule.section)) {
    const items = Array.isArray(resume[rule.section]) ? resume[rule.section] : [];
    items.forEach((item, index) => {
      rule.fields.forEach((field) => {
        requiredCount += 1;
        const path = `${rule.section}.${index}.${field.path}`;
        if (hasValue(getValueByPath(resume, path))) {
          presentCount += 1;
        } else {
          missing.push({
            path,
            label: `${rule.label} #${index + 1} ${field.label}`,
            severity: field.severity,
            suggestion: `建议补充 ${field.label}，否则对应页面字段会跳过。`
          });
        }
      });
    });
    return buildCompletenessSectionPayload(rule, requiredCount, presentCount, missing);
  }

  rule.fields.forEach((field) => {
    requiredCount += 1;
    if (hasValue(getValueByPath(resume, field.path))) {
      presentCount += 1;
    } else {
      missing.push({
        path: field.path,
        label: field.label,
        severity: field.severity,
        suggestion: `建议补充 ${field.label}，否则对应页面字段会跳过。`
      });
    }
  });

  if (!rule.fields.length && rule.minItems) {
    return buildCompletenessSectionPayload(rule, requiredCount, presentCount, missing);
  }

  return buildCompletenessSectionPayload(rule, requiredCount, presentCount, missing);
}

function buildCompletenessSectionPayload(rule, requiredCount, presentCount, missing) {
  return {
    section: rule.section,
    label: rule.label,
    required_count: requiredCount,
    present_count: presentCount,
    missing,
    status: missing.some((item) => item.severity === "critical")
      ? "blocked"
      : missing.length
        ? "needs_attention"
        : "ready"
  };
}

function buildCompletenessWarnings(sections, criticalMissing, mediumMissing) {
  const warnings = [];
  if (criticalMissing.length) {
    warnings.push(`有 ${criticalMissing.length} 个关键字段缺失，建议先补齐再填写真实表单。`);
  }
  if (mediumMissing.length) {
    warnings.push(`有 ${mediumMissing.length} 个重要字段缺失，部分表单可能无法完整填写。`);
  }
  sections.forEach((section) => {
    if (section.required_count && section.present_count === 0) {
      warnings.push(`${section.label} 目前为空。`);
    }
  });
  return warnings;
}

function isRepeatableSection(section) {
  return Boolean(REPEATABLE_CONFIGS[section]);
}

function createMappingContext() {
  return Object.fromEntries(Object.keys(REPEATABLE_CONFIGS).map((type) => [
    type,
    {
      currentIndex: 0,
      seenRoles: new Set()
    }
  ]));
}

function detectRepeatableType(field, lowerText) {
  const explicitType = normalize(field.repeatable_type || "");
  if (REPEATABLE_CONFIGS[explicitType]) {
    return explicitType;
  }

  const dataHints = normalize(`${field.name || ""} ${field.id || ""}`);
  for (const [type, config] of Object.entries(REPEATABLE_CONFIGS)) {
    if (hasAny(dataHints, [type]) || hasAny(lowerText, config.typeTokens)) {
      return type;
    }
  }
  return "";
}

function detectRepeatableRole(type, field, lowerText) {
  const explicitRole = normalize(field.field_role || "");
  if (explicitRole && REPEATABLE_CONFIGS[type].roles[explicitRole]) {
    return explicitRole;
  }

  const config = REPEATABLE_CONFIGS[type];
  for (const [role, tokens] of Object.entries(config.roles)) {
    if (hasAny(lowerText, tokens)) {
      return role;
    }
  }
  return "";
}

function resolveRepeatableIndex(field, type, role, context) {
  const explicit = parseExplicitIndex(field);
  if (explicit != null) {
    return explicit;
  }

  const state = context[type];
  const startRole = REPEATABLE_CONFIGS[type].startRole;
  if (role === startRole && state.seenRoles.has(role)) {
    state.currentIndex += 1;
    state.seenRoles.clear();
  }
  state.seenRoles.add(role);
  return state.currentIndex;
}

function parseExplicitIndex(field) {
  const value = field.repeatable_index;
  if (value !== undefined && value !== null && value !== "" && /^\d+$/.test(String(value))) {
    return Number(value);
  }

  const text = [
    field.name,
    field.id,
    field.selector,
    field.semantic_hints
  ].filter(Boolean).join(" ");
  const patterns = [
    /(?:education|work_experience|projects|project|work|experience)[_-](\d+)[_-]/i,
    /(?:education|work_experience|projects|project|work|experience)[^\d]{0,12}(\d+)/i,
    /(?:第|#)\s*(\d+)\s*(?:条|组)?/i
  ];
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (match) {
      const parsed = Number(match[1]);
      return Number.isFinite(parsed) ? parsed : null;
    }
  }
  return null;
}

function scoreRepeatableField(field, lowerText, type, role) {
  if (field.field_role && normalize(field.field_role) === role) {
    return 0.96;
  }
  if (field.repeatable_type && normalize(field.repeatable_type) === type) {
    return 0.9;
  }
  const roleToken = firstMatchedToken(lowerText, REPEATABLE_CONFIGS[type].roles[role]);
  return roleToken ? scoreByFieldEvidence(field, roleToken) : 0.65;
}

function estimateVisibleGroupCount(type, fields, mappings) {
  const indices = new Set();
  mappings.forEach((mapping) => {
    const match = String(mapping.matched_resume_path || "").match(new RegExp(`^${type}\\.(\\d+)\\.`));
    if (match) {
      indices.add(Number(match[1]));
    }
  });
  if (indices.size) {
    return indices.size;
  }

  const config = REPEATABLE_CONFIGS[type];
  const startRoleCount = fields.filter((field) => {
    const text = normalize(buildSearchText(field));
    return detectRepeatableType(field, text) === type
      && detectRepeatableRole(type, field, text) === config.startRole;
  }).length;
  return startRoleCount;
}

function findAddButton(type, buttons) {
  const safeButtons = buttons.filter((button) => button.selector);
  const config = REPEATABLE_CONFIGS[type];
  const scored = safeButtons.map((button) => ({
    button,
    score: scoreAddButton(type, config, button)
  })).filter((item) => item.score >= 2);

  scored.sort((a, b) => b.score - a.score);
  if (scored[0]) {
    return scored[0].button;
  }
  return safeButtons.length === 1 ? safeButtons[0] : null;
}

function scoreAddButton(type, config, button) {
  const text = normalize([
    button.text,
    button.aria_label,
    button.title,
    button.section,
    button.nearby_context,
    button.semantic_hints
  ].filter(Boolean).join(" "));
  let score = 0;
  if (hasAny(text, ["add", "new", "plus", "新增", "添加", "增加", "+"])) {
    score += 1;
  }
  if (hasAny(text, config.addTokens) || hasAny(text, [type])) {
    score += 2;
  }
  return score;
}

function buildSectionPlanNotes(config, resumeCount, visibleGroupCount, missingGroupCount, addButton) {
  if (!resumeCount) {
    return `简历中没有 ${config.label} 数据。`;
  }
  if (!missingGroupCount) {
    return `${config.label} 已有 ${visibleGroupCount} 组可见字段，可直接填写。`;
  }
  if (addButton) {
    return `检测到 ${config.label} 区域，建议新增 ${missingGroupCount} 组。`;
  }
  return `检测到简历有 ${resumeCount} 条 ${config.label}，页面可见 ${visibleGroupCount} 组，需要手动展开 ${missingGroupCount} 组。`;
}

function formatButtonLabel(button) {
  return button.text || button.aria_label || button.title || button.section || "未命名新增按钮";
}

function exact(path, value, confidence, notes) {
  return {
    path,
    value: stringifyValue(value),
    confidence,
    notes
  };
}

function scoreByFieldEvidence(field, matchedToken) {
  const label = normalize(field.label || "");
  const name = normalize(field.name || "");
  const id = normalize(field.id || "");
  const placeholder = normalize(field.placeholder || "");
  const semanticHints = normalize(field.semantic_hints || "");
  const domContext = normalize(field.dom_context || "");

  if (label.includes(matchedToken)) {
    return 0.95;
  }
  if (name.includes(matchedToken) || id.includes(matchedToken)) {
    return 0.9;
  }
  if (placeholder.includes(matchedToken)) {
    return 0.85;
  }
  if (domContext.includes(matchedToken)) {
    return 0.82;
  }
  if (semanticHints.includes(matchedToken)) {
    return 0.72;
  }
  return 0.75;
}

function buildSearchText(field) {
  return [
    field.label,
    field.placeholder,
    field.name,
    field.id,
    field.section,
    field.dom_context,
    field.semantic_hints,
    field.repeatable_type,
    field.repeatable_index,
    field.field_role,
    field.type,
    field.selector,
    Array.isArray(field.options) ? field.options.map((option) => `${option.text} ${option.value}`).join(" ") : ""
  ].filter(Boolean).join(" ");
}

function bestSemanticLabel(field) {
  const hint = String(field.semantic_hints || "")
    .split(/\s+/)
    .find((item) => /name|email|mail|phone|mobile|school|degree|gpa|github|linkedin|city|location|skill|summary|intro|company|project|education/i.test(item));
  return hint || "";
}

function normalize(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[_\-:：/\\|()[\]{}.,，。;；]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function hasAny(text, tokens) {
  return tokens.some((token) => text.includes(normalize(token)));
}

function firstMatchedToken(text, tokens) {
  return tokens.map(normalize).find((token) => text.includes(token));
}

function stringifyValue(value) {
  if (Array.isArray(value)) {
    return value.filter(Boolean).join("\n");
  }
  if (value && typeof value === "object") {
    if (value.zh || value.en) {
      return value.zh || value.en;
    }
    return Object.values(value).filter(Boolean).join(", ");
  }
  return value == null ? "" : String(value);
}

function hasValue(value) {
  if (Array.isArray(value)) {
    return value.some((item) => hasValue(item));
  }
  if (value && typeof value === "object") {
    return Object.values(value).some((item) => hasValue(item));
  }
  return value !== undefined && value !== null && String(value).trim() !== "";
}

function formatRepeatableValue(value, role) {
  if (role === "tech_stack" && Array.isArray(value)) {
    return value.join(", ");
  }
  if (role === "highlights" && Array.isArray(value)) {
    return value.map((item) => `- ${item}`).join("\n");
  }
  return stringifyValue(value);
}

function extractPhoneCountryCode(phone) {
  const match = String(phone || "").trim().match(/^\+\d{1,4}/);
  return match ? match[0] : "";
}

function formatSkills(skills) {
  if (Array.isArray(skills)) {
    return skills.join(", ");
  }
  if (skills && typeof skills === "object") {
    return Object.values(skills).flat().filter(Boolean).join(", ");
  }
  return "";
}

function buildSelfIntroduction(resume) {
  const summary = stringifyValue(resume.summary);
  if (summary) {
    return summary;
  }

  const personal = resume.personal_info || {};
  const skills = formatSkills(resume.skills);
  const project = getValueByPath(resume, "projects.0.name");
  return [
    personal.degree ? `${personal.degree} candidate` : "Candidate",
    personal.school ? `from ${personal.school}` : "",
    skills ? `with experience in ${skills}` : "",
    project ? `and project experience including ${project}` : ""
  ].filter(Boolean).join(" ");
}

function getValueByPath(source, path) {
  return path.split(".").reduce((current, segment) => {
    if (current == null) {
      return undefined;
    }
    if (/^\d+$/.test(segment)) {
      return Array.isArray(current) ? current[Number(segment)] : undefined;
    }
    return current[segment];
  }, source);
}
