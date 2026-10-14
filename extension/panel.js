const $ = id => document.getElementById(id);
const state = { tab: null, profiles: [], profile: null, record: null, preview: null,
  fields: [], fingerprint: "", uploadFingerprint: "", busy: false, epoch: 0, poll: null };
const STATUS_LABELS = { generating: "生成中", awaiting_confirmation: "待确认", confirmed: "已确认",
  filled: "已填写", partial: "部分填写", failed: "生成失败", expired: "已过期", cancelled: "已取消" };

function status(message, error = false) {
  $("status").textContent = message;
  $("status").classList.toggle("error", error);
}

function baseURL() {
  const url = new URL($("api-base").value.trim());
  if (!["127.0.0.1", "localhost"].includes(url.hostname) || url.protocol !== "http:" || url.username || url.password) {
    throw new Error("当前版本请使用本机 http://127.0.0.1:端口 或 http://localhost:端口。");
  }
  return url.origin;
}

async function api(path, options = {}) {
  if (!state.profile) throw new Error("请先选择已连接的基础档案。");
  const response = await fetch(`${baseURL()}/api/v1/candidate-profiles/${encodeURIComponent(state.profile.id)}${path}`, {
    ...options, headers: { "Content-Type": "application/json", "X-Profile-Token": state.profile.token, ...options.headers }
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `请求失败 (${response.status})，请检查连接及输入内容。`);
  }
  return response;
}

async function jsonAPI(path, options) { return (await api(path, options)).json(); }

async function messageTab(tabId, message) {
  const response = await chrome.tabs.sendMessage(tabId, message);
  if (!response?.ok) throw new Error(response?.error || "页面未响应，请重新识别。");
  return response;
}

async function engine(type, fields, resume, buttons = []) {
  const response = await chrome.runtime.sendMessage({ type, fields, resume, buttons });
  if (!response?.ok) throw new Error(response?.error || "字段映射失败。");
  return response;
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url || !/^https?:/.test(tab.url)) throw new Error("请打开招聘网站的岗位详情或投递页面。");
  return tab;
}

async function install(tabId) {
  await chrome.scripting.executeScript({ target: { tabId }, files: ["content_script.js", "job_context.js"] });
}

function fingerprint(fields) {
  return JSON.stringify(fields.map(field => [field.selector, field.label, field.name, field.type,
    field.required, field.value, field.options, field.repeatable_type, field.repeatable_index]));
}

function clearReview() {
  state.preview = null;
  state.fingerprint = "";
  state.uploadFingerprint = "";
  $("consent").checked = false;
  $("confirm-fill").disabled = true;
  $("mappings").replaceChildren();
  $("report").textContent = "";
}

function stopPolling() {
  clearTimeout(state.poll);
  state.poll = null;
  state.epoch += 1;
}

async function rememberSession(tabId, record) {
  await chrome.storage.local.set({ [`session:${tabId}`]: { id: record.id, profile_id: record.profile_id, page_url: record.page_url } });
}

async function connect() {
  stopPolling();
  const origin = baseURL();
  const tabs = await chrome.tabs.query({});
  const tab = tabs.find(item => {
    try { const url = new URL(item.url); return url.origin === origin && url.pathname.startsWith("/app/"); }
    catch { return false; }
  });
  if (!tab) throw new Error("请先打开此服务的 NoWorryCV 网页，并保存基础档案，再点击连接。");
  const [result] = await chrome.scripting.executeScript({ target: { tabId: tab.id },
    func: () => JSON.parse(localStorage.getItem("noworrycv-candidate-archives") || "[]") });
  const profiles = (result.result || []).filter(item => item.id && item.token && item.label);
  if (!profiles.length) throw new Error("网页尚未保存基础档案，请先上传、确认并保存资料。");
  state.profiles = profiles;
  await chrome.storage.local.set({ connection: { base: origin, profiles } });
  renderProfiles();
  await chooseProfile();
  status("基础档案已连接。请切到招聘页面识别岗位。");
}

function renderProfiles(selected = state.profiles[0]?.id) {
  $("profiles").replaceChildren();
  for (const profile of state.profiles) {
    const option = document.createElement("option");
    option.value = profile.id; option.textContent = profile.label;
    $("profiles").appendChild(option);
  }
  $("profiles").value = selected || "";
}

async function chooseProfile() {
  stopPolling(); clearReview();
  state.profile = state.profiles.find(item => item.id === $("profiles").value) || null;
  state.record = null; $("review").hidden = true;
  if (!state.profile) return;
  const archive = await jsonAPI("");
  state.profile.revision = archive.revision;
  await chrome.storage.local.set({ selectedProfile: state.profile.id });
  await refreshHistory();
}

async function detect() {
  const tab = await activeTab();
  if (state.record && (state.record.page_url !== tab.url || state.tab?.id !== tab.id)) {
    stopPolling(); clearReview(); state.record = null; $("review").hidden = true;
  }
  state.tab = tab;
  await install(tab.id);
  const { job } = await messageTab(tab.id, { type: "EXTRACT_JOB_CONTEXT" });
  $("page").textContent = job.page_url;
  $("job-source").textContent = `识别来源：${job.source}`;
  $("company").value = job.target_company; $("role").value = job.target_role; $("jd").value = job.jd_text;
  if (job.jd_text.length >= 20) await chrome.storage.local.set({ lastJob: job });
  renderUploads(job.upload_inputs);
  status(job.jd_text ? "已识别岗位。请检查要求后生成简历。" : job.source);
  if ($("auto-generate").checked && state.profile && !state.record && job.jd_text.length >= 20) {
    const { fields } = await messageTab(tab.id, { type: "EXTRACT_FIELDS" });
    const basics = fields.filter(field => /姓名|邮箱|电话|full.?name|email|phone/i.test(`${field.label} ${field.name}`));
    const hasResume = job.upload_inputs.some(input => /简历|resume|curriculum/i.test(input.label));
    if (basics.length >= 2 || hasResume) await generate();
  }
}

function renderUploads(inputs, preserve = false) {
  const previous = preserve ? $("upload").value : "";
  $("upload").replaceChildren(new Option("不自动上传附件", ""));
  for (const input of inputs) {
    if (input.disabled) continue;
    $("upload").add(new Option(`${input.label} ${input.accept || ""}`, input.selector));
  }
  if (previous && [...$("upload").options].some(item => item.value === previous)) $("upload").value = previous;
  else {
    const resumes = inputs.filter(item => !item.disabled && /简历|resume|curriculum/i.test(item.label));
    if (resumes.length === 1) $("upload").value = resumes[0].selector;
  }
}

async function generate() {
  const tab = await activeTab();
  await install(tab.id); state.tab = tab;
  const archive = await jsonAPI("");
  const jd = $("jd").value.trim();
  if (jd.length < 20) throw new Error("岗位要求过短，请识别岗位详情或补充完整 JD。");
  stopPolling(); clearReview();
  const { lastJob } = await chrome.storage.local.get("lastJob");
  const record = await jsonAPI("/applications", {
    method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify({ page_url: tab.url, job_url: lastJob?.jd_text === jd ? lastJob.job_url : tab.url,
      jd_text: jd, target_company: $("company").value, target_role: $("role").value,
      expected_revision: archive.revision })
  });
  state.record = record;
  await rememberSession(tab.id, record);
  status("已开始生成微调简历，可关闭侧栏后继续查看。");
  pollRecord(state.epoch);
}

async function pollRecord(epoch) {
  if (epoch !== state.epoch || !state.record) return;
  try {
    const record = await jsonAPI(`/applications/${state.record.id}`);
    if (epoch !== state.epoch) return;
    state.record = record;
    if (record.status === "generating") {
      status(`${record.progress_percent}% · ${record.status_message || "正在微调简历…"}`);
      state.poll = setTimeout(() => pollRecord(epoch), 2000);
    } else if (record.draft) {
      renderRecord();
      const tab = await activeTab();
      if (tab.url === record.page_url) { state.tab = tab; await prepare(); }
      status(record.confirmed_at ? "已恢复保存的简历版本。" : "微调简历已生成，请检查简历和填写预览后确认。");
      await refreshHistory();
    } else { status(record.status_message || "生成失败，请重新创建任务。", true); }
  } catch (error) {
    status(`${error.message} 点击“刷新记录”可恢复进度。`, true);
  }
}

function renderRecord() {
  $("review").hidden = false;
  $("company").value = state.record.target_company;
  $("role").value = state.record.target_role;
  $("jd").value = state.record.jd_text;
  $("draft").textContent = state.record.form_resume.resume_text || state.record.draft.markdown;
  $("changes").textContent = state.record.change_log.join("\n");
  $("risks").textContent = state.record.risk_notes.length ? `需检查：\n${state.record.risk_notes.join("\n")}` : "";
  $("edit-draft").disabled = Boolean(state.record.confirmed_at);
  $("download").disabled = !state.record.confirmed_at;
}

async function prepare() {
  if (!state.record?.draft) throw new Error("请先生成微调简历。");
  const tab = await activeTab();
  if (tab.url !== state.record.page_url) throw new Error("当前页面与此投递记录不同，请回到原投递页面。");
  state.tab = tab; await install(tab.id);
  clearReview();
  // Reload before previewing to catch any draft edits saved in the web editor.
  state.record = await jsonAPI(`/applications/${state.record.id}`); renderRecord();
  let fields = (await messageTab(tab.id, { type: "EXTRACT_FIELDS" })).fields;
  const buttons = (await messageTab(tab.id, { type: "EXTRACT_ACTION_BUTTONS" })).buttons;
  const { plan } = await engine("PLAN_FORM", fields, state.record.form_resume, buttons);
  if ($("expand").checked) {
    for (const section of plan.repeatable_sections || []) {
      if (!section.add_button_selector) continue;
      for (let i = 0; i < Math.min(section.missing_group_count, 20); i++) {
        await messageTab(tab.id, { type: "CLICK_ACTION", selector: section.add_button_selector });
      }
    }
    fields = (await messageTab(tab.id, { type: "EXTRACT_FIELDS" })).fields;
  }
  state.fields = fields;
  state.fingerprint = fingerprint(fields);
  state.preview = (await engine("BUILD_FILL_PREVIEW", fields, state.record.form_resume)).preview;
  for (const item of state.preview.items) {
    if (["radio", "checkbox", "password"].includes(item.field_type)) {
      item.enabled = false;
      item.notes = "此控件需在招聘页面手动处理。";
    }
  }
  const missing = state.preview.items.filter(item => !item.enabled).length;
  $("plan").textContent = `识别 ${fields.length} 个字段，${missing} 个尚未启用或缺少资料。请检查并补充。 ${plan.warnings.join(" ")}`;
  const { job } = await messageTab(tab.id, { type: "EXTRACT_JOB_CONTEXT" });
  renderUploads(job.upload_inputs, true);
  state.uploadFingerprint = JSON.stringify(job.upload_inputs);
  renderMappings(); updateConfirm();
}

function renderMappings() {
  $("mappings").replaceChildren();
  for (const item of state.preview.items) {
    const row = document.createElement("div"); row.className = "mapping";
    const label = document.createElement("label");
    const check = document.createElement("input"); check.type = "checkbox"; check.checked = item.enabled;
    label.append(check, ` ${item.field_label}`);
    const value = document.createElement("textarea"); value.rows = 2; value.value = item.fill_value;
    const hint = document.createElement("small");
    hint.textContent = ["radio", "checkbox", "password"].includes(item.field_type)
      ? "请在招聘页面手动处理此控件。"
      : item.matched_resume_path ? `匹配程度 ${Math.round(item.confidence * 100)}% · 来自基础资料或微调简历，请核对`
      : "未找到可用资料，请补充或跳过";
    const change = () => {
      item.enabled = check.checked; item.fill_value = value.value; item.edited = true;
      if (value.value.trim() && !item.matched_resume_path) item.matched_resume_path = "user_input";
      // An explicit user edit can approve a field which rules could not recognize.
      if (check.checked && value.value.trim()) item.confidence = 1;
      $("consent").checked = false; updateConfirm();
    };
    check.addEventListener("change", change); value.addEventListener("input", change);
    row.append(label, value, hint); $("mappings").append(row);
  }
}

function updateConfirm() {
  $("confirm-fill").disabled = state.busy || !state.preview || !$("consent").checked;
}

async function confirmAndFill() {
  const tab = await activeTab();
  const record = state.record;
  if (!state.preview || !$("consent").checked) throw new Error("请先检查填写预览并勾选确认。");
  if (tab.id !== state.tab.id || tab.url !== record.page_url) throw new Error("页面已切换，请回到预览对应的投递页面。");
  const fields = (await messageTab(tab.id, { type: "EXTRACT_FIELDS" })).fields;
  const { job } = await messageTab(tab.id, { type: "EXTRACT_JOB_CONTEXT" });
  if (fingerprint(fields) !== state.fingerprint || JSON.stringify(job.upload_inputs) !== state.uploadFingerprint) {
    await prepare(); throw new Error("页面字段或值已变化，已刷新预览，请重新检查确认。");
  }
  const previewItems = structuredClone(state.preview.items);
  const uploadSelector = $("upload").value;
  const format = $("format").value;
  state.record = await jsonAPI(`/applications/${record.id}/confirm`, { method: "POST", body: JSON.stringify({
    draft_digest: record.draft_digest, confirmed: true, storage_consent: true }) });
  renderRecord();
  const current = await chrome.tabs.get(tab.id);
  if (current.url !== record.page_url) throw new Error("简历已保存，但页面已跳转，请回到投递页面再填写。");
  const result = await messageTab(tab.id, { type: "FILL_FIELDS", page_url: record.page_url, mappings: previewItems });
  const skipReasons = { skipped_disabled_by_user: "已在预览中关闭", skipped_empty: "缺少可填写资料",
    skipped_low_confidence: "匹配不确定，请人工检查", skipped_disabled: "字段不可用或只读" };
  const outcomes = (result.results || []).map(item => ({ selector: item.selector || "", field_label: item.field_label || "",
    status: item.status === "filled" ? "filled" : item.status === "failed" ? "failed" : "skipped", reason: skipReasons[item.status] || item.reason || "" }));
  if (uploadSelector) {
    try {
      const blob = await (await api(`/applications/${record.id}/resume/${format}`)).blob();
      const data = await blobBase64(blob);
      const uploaded = await messageTab(tab.id, { type: "ATTACH_CONFIRMED_RESUME", selector: uploadSelector,
        page_url: record.page_url, filename: `tailored-resume.${format}`, media_type: blob.type, data });
      outcomes.push({ selector: uploadSelector, field_label: "微调简历附件", status: "filled", reason: uploaded.filename });
    } catch (error) { outcomes.push({ selector: uploadSelector, field_label: "微调简历附件", status: "failed", reason: error.message }); }
  }
  const report = { page_url: record.page_url, results: outcomes };
  // Keep a retryable report if the network drops after changing the page.
  await chrome.storage.local.set({ [`report:${record.id}`]: report });
  state.record = await jsonAPI(`/applications/${record.id}/fill-report`, { method: "POST", body: JSON.stringify(report) });
  await chrome.storage.local.remove(`report:${record.id}`);
  const filled = outcomes.filter(item => item.status === "filled").length;
  $("report").textContent = `已填写 ${filled} 项；需检查 ${outcomes.length - filled} 项。\n` + outcomes.filter(item => item.status !== "filled").map(item => `${item.field_label}: ${item.reason}`).join("\n");
  clearReviewAfterFill(); await refreshHistory();
  status("简历与填写结果已保存。请核对招聘页面后手动提交。");
}

function clearReviewAfterFill() { state.preview = null; $("consent").checked = false; updateConfirm(); }

async function blobBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(",")[1]); reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

async function download(record = state.record) {
  if (!record?.confirmed_at) throw new Error("请先确认简历再下载。");
  const format = $("format").value;
  const blob = await (await api(`/applications/${record.id}/resume/${format}`)).blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a"); link.href = url; link.download = `tailored-resume.${format}`; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

async function refreshHistory() {
  const records = await jsonAPI("/applications");
  $("history").replaceChildren();
  for (const record of records) {
    const row = document.createElement("div"); row.className = "history-item";
    const text = document.createElement("p");
    text.textContent = `${record.target_company} · ${record.target_role || "未命名岗位"} · ${STATUS_LABELS[record.status] || record.status}`;
    const view = document.createElement("button"); view.textContent = "查看 / 恢复";
    view.addEventListener("click", () => action(async () => {
      stopPolling(); clearReview(); state.record = record;
      $("page").textContent = record.page_url;
      const pending = (await chrome.storage.local.get(`report:${record.id}`))[`report:${record.id}`];
      if (pending) {
        state.record = await jsonAPI(`/applications/${record.id}/fill-report`, { method: "POST", body: JSON.stringify(pending) });
        await chrome.storage.local.remove(`report:${record.id}`);
      }
      pollRecord(state.epoch);
    }));
    row.append(text, view);
    if (record.confirmed_at) {
      const button = document.createElement("button"); button.textContent = "下载简历";
      button.addEventListener("click", () => action(() => download(record))); row.append(button);
    }
    const remove = document.createElement("button"); remove.textContent = "删除";
    remove.addEventListener("click", () => action(async () => {
      if (!window.confirm("删除这次投递记录及对应生成任务？")) return;
      await api(`/applications/${record.id}`, { method: "DELETE" });
      await chrome.storage.local.remove(`report:${record.id}`);
      if (state.record?.id === record.id) { stopPolling(); clearReview(); state.record = null; $("review").hidden = true; }
      await refreshHistory();
    })); row.append(remove); $("history").append(row);
  }
  if (!records.length) $("history").textContent = "暂无投递记录。";
}

async function action(fn) {
  if (state.busy) return;
  state.busy = true;
  const controls = [...document.querySelectorAll("button, input, textarea, select")];
  const disabledStates = controls.map(control => control.disabled);
  controls.forEach(control => { control.disabled = true; });
  try { await fn(); } catch (error) { status(error.message || String(error), true); }
  finally {
    state.busy = false; controls.forEach((control, index) => { control.disabled = disabledStates[index]; });
    if (state.record?.draft) renderRecord();
    updateConfirm();
  }
}

$("open-app").addEventListener("click", () => action(() => chrome.tabs.create({ url: `${baseURL()}/app/` })));
$("connect").addEventListener("click", () => action(connect));
$("profiles").addEventListener("change", () => action(chooseProfile));
$("detect").addEventListener("click", () => action(detect));
$("generate").addEventListener("click", () => action(generate));
$("prepare").addEventListener("click", () => action(prepare));
$("confirm-fill").addEventListener("click", () => action(confirmAndFill));
$("download").addEventListener("click", () => action(() => download()));
$("history-refresh").addEventListener("click", () => action(async () => {
  if (state.record) { stopPolling(); pollRecord(state.epoch); }
  await refreshHistory();
}));
$("edit-draft").addEventListener("click", () => action(async () => {
  if (!state.record || state.record.confirmed_at) throw new Error("已确认快照已保存；如需更改，请创建新的投递版本。");
  await chrome.tabs.create({ url: `${baseURL()}/app/?run=${encodeURIComponent(state.record.run_id)}&profile=${encodeURIComponent(state.profile.id)}` });
}));
$("undo").addEventListener("click", () => action(async () => {
  const tab = await activeTab(); await install(tab.id);
  const result = await messageTab(tab.id, { type: "UNDO_LAST_FILL" });
  status(`已撤销 ${result.restored_count || 0} 个文本字段。附件请在招聘页面移除；已确认简历仍保留。`);
  clearReview();
}));
$("consent").addEventListener("change", updateConfirm);
for (const id of ["company", "role", "jd"]) $(id).addEventListener("input", () => {
  if (!state.record) return;
  stopPolling(); clearReview(); state.record = null; $("review").hidden = true;
  status("岗位信息已修改，请重新生成对应版本；原版本可在记录列表恢复。");
});
$("auto-generate").addEventListener("change", () => chrome.storage.local.set({ autoGenerate: $("auto-generate").checked }));
$("upload").addEventListener("change", () => { $("consent").checked = false; updateConfirm(); });
$("format").addEventListener("change", () => { $("consent").checked = false; updateConfirm(); });
$("api-base").addEventListener("change", () => {
  stopPolling(); clearReview(); state.profile = null; state.record = null; state.profiles = [];
  $("review").hidden = true; renderProfiles(); $("history").replaceChildren();
  status("服务地址已变化，请重新连接基础档案。");
});
$("reuse-job").addEventListener("click", () => action(async () => {
  const { lastJob } = await chrome.storage.local.get("lastJob");
  if (!lastJob) throw new Error("请先在岗位详情页识别并检查岗位。");
  $("company").value = lastJob.target_company; $("role").value = lastJob.target_role; $("jd").value = lastJob.jd_text;
  $("job-source").textContent = `沿用岗位来源：${lastJob.job_url}`;
  status("已沿用上次岗位。请确认它与当前投递页面对应。");
}));

async function restore() {
  const saved = await chrome.storage.local.get(["connection", "selectedProfile", "autoGenerate"]);
  $("auto-generate").checked = saved.autoGenerate !== false;
  if (saved.connection) {
    $("api-base").value = saved.connection.base; state.profiles = saved.connection.profiles;
    renderProfiles(saved.selectedProfile || state.profiles[0]?.id); await chooseProfile();
  }
  const tab = await activeTab(); state.tab = tab;
  $("page").textContent = tab.url;
  const session = (await chrome.storage.local.get(`session:${tab.id}`))[`session:${tab.id}`];
  if (session && session.page_url === tab.url && session.profile_id === state.profile?.id) {
    state.record = { id: session.id }; pollRecord(state.epoch);
  } else if (state.profile) { await detect(); }
  else { status("请先在 NoWorryCV 网页保存基础档案并连接。"); }
}

chrome.tabs.onActivated.addListener(() => {
  if (state.busy) return;
  stopPolling(); clearReview(); state.record = null; $("review").hidden = true;
  action(restore);
});
chrome.tabs.onUpdated.addListener((tabId, change) => {
  if (tabId === state.tab?.id && change.url && change.url !== state.tab.url) {
    stopPolling(); clearReview(); state.record = null; $("review").hidden = true;
    state.tab.url = change.url;
    $("page").textContent = change.url; status("页面已跳转，请重新识别当前投递页面。");
  }
  if (tabId === state.tab?.id && change.status === "complete" && !state.busy && state.profile && !state.record) action(restore);
});
action(restore);
