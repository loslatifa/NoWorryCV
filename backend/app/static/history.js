const historyList = document.getElementById("history-list");
const historyMessage = document.getElementById("history-message");
const historySearch = document.getElementById("history-search");
const historyStatusFilter = document.getElementById("history-status-filter");
const historyArchiveFilter = document.getElementById("history-archive-filter");
const historySort = document.getElementById("history-sort");
const versionLabel = document.getElementById("version-label");
const versionManagementStatus = document.getElementById("version-management-status");
let historyItems = [];
let historyRequestSequence = 0;
let historySearchTimer = null;
let comparisonLoads = 0;
let comparisonInProgress = false;

function updateComparisonAvailability() {
  document.getElementById("compare-versions-button").disabled = comparisonInProgress || comparisonLoads > 0
    || !document.getElementById("compare-before-version").value
    || !document.getElementById("compare-after-version").value;
}

function rememberedHistoryRuns() {
  try {
    const saved = JSON.parse(localStorage.getItem("noworrycv-run-history") || "[]");
    if (!Array.isArray(saved)) return [];
    const valid = saved.filter((item) => item.id && item.token && item.expiresAt && new Date(item.expiresAt).getTime() > Date.now());
    if (valid.length !== saved.length) localStorage.setItem("noworrycv-run-history", JSON.stringify(valid));
    return valid;
  } catch (_error) { return []; }
}

function historyRunToken(item) {
  const remembered = rememberedHistoryRuns().find((entry) => entry.id === item.run_id);
  return remembered?.token || archiveCredentials.find((entry) => entry.id === item.candidate_archive_id)?.token || "";
}

function historyHeaders(item) {
  return {"Content-Type": "application/json", "X-Run-Token": historyRunToken(item)};
}

function forgetHistoryRun(runId) {
  try {
    localStorage.setItem("noworrycv-run-history", JSON.stringify(rememberedHistoryRuns().filter((item) => item.id !== runId)));
  } catch (_error) { /* The server still enforces deletion and expiry. */ }
  refreshRunHistory();
}

function historyButton(label, onClick, danger = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = danger ? "danger-button" : "secondary-button";
  button.textContent = label;
  button.addEventListener("click", async () => {
    button.disabled = true;
    try { await onClick(); }
    catch (error) { historyMessage.textContent = error.message; }
    finally { button.disabled = false; }
  });
  return button;
}

async function updateHistoryItem(item, changes) {
  const response = await fetch(`/api/v1/tailor-runs/${item.run_id}/metadata`, {
    method: "PATCH", headers: historyHeaders(item), body: JSON.stringify(changes),
  });
  if (!response.ok) throw new Error(await getResponseError(response, "任务信息更新失败。"));
  await refreshRunHistory();
}

async function openHistoryRun(item) {
  if (runIsBusy || draftMutationInProgress || draftIsDirty) throw new Error("请先完成当前任务和版本操作，并保存编辑，再打开历史任务。");
  currentRunId = item.run_id;
  currentRunToken = historyRunToken(item);
  currentRunExpiresAt = item.expires_at;
  persistActiveRun();
  previewData = null;
  confirmationPanel.classList.add("hidden");
  document.body.classList.remove("review-mode");
  document.getElementById("jd-text").value = item.jd_text;
  document.getElementById("target-company").value = item.company;
  document.getElementById("target-role").value = item.job_title;
  taskRetention.textContent = `此任务预计在 ${new Date(item.expires_at).toLocaleString()} 自动删除；归档不会延长保存期限。`;
  startWaitingExperience(item.jd_text);
  try {
    const result = await pollRunStatus(item.run_id);
    renderResult(result);
    setStatus(`已恢复「${item.job_title || "历史任务"}」，可继续编辑和导出。`, "success");
    stopWaitingExperience(true);
  } catch (error) {
    stopWaitingExperience(false);
    if (currentRunId !== item.run_id) return;
    setStatus(error.message || "历史任务载入失败。", "error");
    if (!error.recoverable) {
      waitingPanel.classList.add("hidden");
      form.classList.remove("hidden");
    }
  }
}

function renderHistoryItems() {
  historyList.replaceChildren();
  const statusNames = {queued: "排队中", running: "运行中", completed: "已完成", failed: "失败", cancelled: "已取消"};
  historyItems.forEach((item) => {
    const card = document.createElement("article");
    card.className = "history-card";
    card.dataset.runId = item.run_id;
    const heading = document.createElement("h4");
    heading.textContent = `${item.company || "未填写公司"} · ${item.job_title || "待识别岗位"}`;
    const meta = document.createElement("p");
    meta.className = "review-help";
    meta.textContent = `${statusNames[item.status] || item.status}${item.archived ? " · 已归档" : ""} · ${new Date(item.created_at).toLocaleString()} · ${item.version_count} 个版本`;
    const actions = document.createElement("div");
    actions.className = "history-card-actions";
    actions.append(historyButton(item.status === "completed" ? "恢复编辑" : "查看进度 / 恢复任务", () => openHistoryRun(item)));
    actions.append(historyButton(item.archived ? "取消归档任务" : "归档任务", () => updateHistoryItem(item, {archived: !item.archived})));
    actions.append(historyButton("删除任务", async () => {
      if (item.run_id === currentRunId) { deleteRunButton.click(); return; }
      if (!window.confirm("确定删除此任务及全部简历版本？删除后无法恢复。")) return;
      const response = await fetch(`/api/v1/tailor-runs/${item.run_id}`, {method: "DELETE", headers: historyHeaders(item)});
      if (!response.ok) throw new Error(await getResponseError(response, "任务删除失败。"));
      forgetHistoryRun(item.run_id);
    }, true));
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "查看对应 JD / 修改公司与岗位";
    details.appendChild(summary);
    const jd = document.createElement("pre");
    jd.className = "history-jd";
    jd.textContent = item.jd_text || "此旧任务未保存完整 JD，请参考任务内的岗位分析。";
    const company = makeHistoryField("公司", item.company);
    const role = makeHistoryField("岗位", item.job_title);
    details.append(jd, company.wrapper, role.wrapper, historyButton("保存任务名称", () => updateHistoryItem(item, {company: company.input.value, job_title: role.input.value})));
    card.append(heading, meta, actions, details);
    historyList.appendChild(card);
  });
}

function makeHistoryField(label, value) {
  const wrapper = document.createElement("label");
  wrapper.className = "field compact";
  const span = document.createElement("span");
  span.textContent = label;
  const input = document.createElement("input");
  input.type = "text";
  input.maxLength = 120;
  input.value = value;
  wrapper.append(span, input);
  return {wrapper, input};
}

async function refreshRunHistory() {
  const sequence = ++historyRequestSequence;
  try {
    const response = await fetch("/api/v1/tailor-runs/history", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        runs: rememberedHistoryRuns().map(({id, token}) => ({id, token})),
        archives: archiveCredentials.map(({id, token}) => ({id, token})),
        search: historySearch.value, status: historyStatusFilter.value,
        archive_filter: historyArchiveFilter.value, sort: historySort.value,
      }),
    });
    if (!response.ok) throw new Error(await getResponseError(response, "无法载入任务历史。"));
    const payload = await response.json();
    if (sequence !== historyRequestSequence) return;
    historyItems = payload.items;
    if (payload.unavailable_run_ids.length) {
      try {
        localStorage.setItem("noworrycv-run-history", JSON.stringify(rememberedHistoryRuns().filter((item) => !payload.unavailable_run_ids.includes(item.id))));
      } catch (_error) { /* Unavailable tasks are already absent from the list. */ }
    }
    historyMessage.textContent = historyItems.length ? `${historyItems.length} 个任务；到期时间可在打开任务后查看。` : "没有符合条件的任务。已过期或已删除的任务会自动移除。";
    renderHistoryItems();
    await refreshComparisonTasks();
  } catch (error) {
    if (sequence === historyRequestSequence) historyMessage.textContent = error.message;
  }
}

async function refreshComparisonTasks() {
  for (const side of ["before", "after"]) {
    const select = document.getElementById(`compare-${side}-run`);
    const previous = select.value;
    select.replaceChildren();
    historyItems.filter((item) => item.status === "completed" && item.version_count).forEach((item) => {
      const option = document.createElement("option");
      option.value = item.run_id;
      option.textContent = `${item.company || "未填写公司"} · ${item.job_title || "定制任务"}`;
      select.appendChild(option);
    });
    if ([...select.options].some((option) => option.value === previous)) select.value = previous;
    await loadComparisonVersions(side);
  }
}

async function loadComparisonVersions(side) {
  comparisonLoads += 1;
  updateComparisonAvailability();
  try {
    const runId = document.getElementById(`compare-${side}-run`).value;
    const item = historyItems.find((entry) => entry.run_id === runId);
    const select = document.getElementById(`compare-${side}-version`);
    const previous = select.value;
    select.replaceChildren();
    if (!item) return;
    const response = await fetch(`/api/v1/tailor-runs/${runId}/draft-versions`, {headers: historyHeaders(item)});
    if (!response.ok) return;
    const versions = await response.json();
    if (document.getElementById(`compare-${side}-run`).value !== runId) return;
    versions.forEach((version) => {
      const option = document.createElement("option");
      option.value = version.id;
      option.textContent = `${version.label}${version.archived ? " · 已归档" : ""} · ${new Date(version.created_at).toLocaleString()}`;
      select.appendChild(option);
    });
    if (versions.some((version) => version.id === previous)) select.value = previous;
    else if (side === "after" && select.options.length) select.selectedIndex = select.options.length - 1;
  } finally {
    comparisonLoads -= 1;
    updateComparisonAvailability();
  }
}

function updateVersionManagement() {
  const version = draftVersions.find((entry) => entry.id === draftVersionSelect.value);
  versionLabel.value = version?.label || "";
  document.getElementById("archive-version-button").textContent = version?.archived ? "取消归档所选版本" : "归档所选版本";
}

async function manageSelectedVersion(action) {
  const selectedId = draftVersionSelect.value;
  const selected = draftVersions.find((entry) => entry.id === selectedId);
  if (!currentRunId || !selected) return;
  if (draftIsDirty) throw new Error("请先保存当前编辑，再管理历史版本。");
  if (action === "delete" && !window.confirm(`确定删除版本「${selected.label}」？删除后无法恢复。`)) return;
  const method = action === "delete" ? "DELETE" : action === "copy" ? "POST" : "PATCH";
  const response = await fetch(`/api/v1/tailor-runs/${currentRunId}/draft-versions/${selectedId}${action === "copy" ? "/copy" : ""}`, {
    method, headers: runRequestHeaders(),
    ...(method === "PATCH" ? {body: JSON.stringify(action === "rename" ? {label: versionLabel.value.trim()} : {archived: !selected.archived})} : {}),
  });
  if (!response.ok) throw new Error(await getResponseError(response, "版本管理失败。"));
  if (action === "delete") {
    const versionsResponse = await fetch(`/api/v1/tailor-runs/${currentRunId}/draft-versions`, {headers: runRequestHeaders(false)});
    if (!versionsResponse.ok) throw new Error("版本已删除，请刷新历史版本列表。");
    draftVersions = await versionsResponse.json();
  } else {
    const payload = await response.json();
    draftVersions = payload.versions;
    activeVersionId = payload.active_version_id;
  }
  renderVersionOptions();
  if (action === "copy") draftVersionSelect.value = draftVersions[draftVersions.length - 1].id;
  else if (action !== "delete") draftVersionSelect.value = selectedId;
  updateVersionManagement();
  versionManagementStatus.textContent = {rename: "版本名称已保存。", copy: "版本副本已创建；恢复此版本后可继续编辑。", archive: selected.archived ? "已取消归档。" : "版本已归档，仍可恢复和对比。", delete: "版本已删除。"}[action];
  await refreshRunHistory();
}

for (const [buttonId, action] of [["rename-version-button", "rename"], ["copy-version-button", "copy"], ["archive-version-button", "archive"], ["delete-version-button", "delete"]]) {
  const button = document.getElementById(buttonId);
  button.addEventListener("click", async () => {
    if (draftMutationInProgress) { versionManagementStatus.textContent = "请先等待当前版本操作完成。"; return; }
    draftMutationInProgress = true;
    button.disabled = true;
    try { await manageSelectedVersion(action); }
    catch (error) { versionManagementStatus.textContent = error.message; }
    finally { button.disabled = false; draftMutationInProgress = false; }
  });
}

draftVersionSelect.addEventListener("change", updateVersionManagement);
document.getElementById("refresh-history-button").addEventListener("click", refreshRunHistory);
for (const filter of [historyStatusFilter, historyArchiveFilter, historySort]) filter.addEventListener("change", refreshRunHistory);
historySearch.addEventListener("input", () => {
  clearTimeout(historySearchTimer);
  historySearchTimer = setTimeout(refreshRunHistory, 250);
});
for (const side of ["before", "after"]) document.getElementById(`compare-${side}-run`).addEventListener("change", () => loadComparisonVersions(side));

document.getElementById("compare-versions-button").addEventListener("click", async () => {
  const button = document.getElementById("compare-versions-button");
  const status = document.getElementById("version-comparison-status");
  const result = document.getElementById("version-comparison-result");
  comparisonInProgress = true;
  button.disabled = true;
  result.replaceChildren();
  try {
    const references = {};
    for (const side of ["before", "after"]) {
      const item = historyItems.find((entry) => entry.run_id === document.getElementById(`compare-${side}-run`).value);
      const versionId = document.getElementById(`compare-${side}-version`).value;
      if (!item || !versionId) throw new Error("请选择两个有效的已保存版本。它们可以来自同一个任务。");
      references[side] = {run_id: item.run_id, version_id: versionId, access_token: historyRunToken(item)};
    }
    const response = await fetch("/api/v1/tailor-runs/version-comparison", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(references)});
    if (!response.ok) throw new Error(await getResponseError(response, "版本对比失败。"));
    const payload = await response.json();
    status.textContent = `${payload.before_job_title} · ${payload.before_label} → ${payload.after_job_title} · ${payload.after_label}：${payload.differences.length ? `${payload.differences.length} 处变化` : "内容一致"}`;
    payload.differences.forEach((diff) => {
      const card = document.createElement("article");
      card.className = "version-comparison-card";
      const heading = document.createElement("h4");
      heading.textContent = `${diff.label} · ${{added: "新增", removed: "删除", modified: "修改"}[diff.change_type]}`;
      const columns = document.createElement("div");
      columns.className = "version-comparison-columns";
      for (const [label, value] of [["原版本", diff.before_text], ["新版本", diff.after_text]]) {
        const cell = document.createElement("div");
        const title = document.createElement("strong");
        title.textContent = label;
        const text = document.createElement("pre");
        text.textContent = value || "（空）";
        cell.append(title, text);
        columns.appendChild(cell);
      }
      card.append(heading, columns);
      result.appendChild(card);
    });
  } catch (error) { status.textContent = error.message; }
  finally { comparisonInProgress = false; updateComparisonAvailability(); }
});

try {
  const active = JSON.parse(sessionStorage.getItem("noworrycv-active-run") || "null");
  if (active?.runId && active.token) rememberCurrentRun();
} catch (_error) { /* History can still be loaded through saved archive credentials. */ }
refreshRunHistory();
