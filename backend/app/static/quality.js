(function installQualityUI() {
  const byId = id => document.getElementById(id);
  const reasonNames = { none: "无特别问题", accuracy: "事实准确性", relevance: "岗位相关性", clarity: "表达清晰度", format: "排版与格式", missing_information: "信息遗漏" };
  let feedback = [], feedbackSequence = 0, dashboardSequence = 0;
  let selectedRun = "", selectedVersion = "";
  const percent = value => value == null ? "暂无数据" : `${(value * 100).toFixed(1)}%`;

  async function request(runId, path, body) {
    const response = await fetch(`/api/v1/tailor-runs/${encodeURIComponent(runId)}${path}`, {
      method: body ? "POST" : "GET", headers: runRequestHeaders(),
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "反馈未保存，请检查所选版本后重试。");
    return result;
  }

  function restoreRating() {
    const saved = feedback.find(item => item.scope === "result" && item.version_id === selectedVersion);
    byId("result-feedback-rating").value = saved ? String(saved.rating) : "";
    byId("result-feedback-reason").value = saved?.reason || "none";
    byId("result-feedback-status").textContent = saved ? "已载入此版本的评价，可修改后重新保存。" : "当前已保存版本尚未评价。";
  }

  function versionText(item, label) {
    if (!item) return `${label}：旧版本未记录生成环境。`;
    return `${label}：${item.provider} / ${item.model}；提示词 ${item.prompt_version}（${(item.prompt_digest || "unknown").slice(0, 12)}）；评分 ${item.scoring_version}；版本 ${(item.fingerprint || "unknown").slice(0, 12)}`;
  }

  window.initializeQualityFeedback = async function(runId, versionId, provenance, provenanceHistory = [], version = null) {
    selectedRun = runId; selectedVersion = versionId;
    const sequence = ++feedbackSequence;
    feedback = []; restoreRating();
    const versions = provenanceHistory.length ? provenanceHistory : [provenance];
    byId("generation-provenance").textContent = versions.filter(Boolean).map((item, index) => versionText(item, index ? "恢复阶段环境" : "初始生成环境")).join("\n")
      + (version ? "\n" + versionText(version.provenance, "当前保存版本环境") : "");
    try {
      const records = await request(runId, "/feedback");
      if (sequence !== feedbackSequence) return;
      feedback = records; restoreRating();
    } catch (error) {
      if (sequence === feedbackSequence) byId("result-feedback-status").textContent = error.message;
    }
  };

  window.changeQualityVersion = function(version) {
    selectedVersion = version.id; restoreRating();
    const source = {generated:"AI 生成", manual:"手工编辑", ai_partial:"局部重写", copied:"复制版本"}[version.source] || version.source;
    byId("generation-provenance").textContent = versionText(version.provenance, `${source}版本环境`);
  };

  byId("result-feedback-submit").addEventListener("click", async () => {
    const message = byId("result-feedback-status");
    const rating = Number(byId("result-feedback-rating").value);
    if (!selectedRun || !selectedVersion || !rating) { message.textContent = "请先选择已保存版本和评分。"; return; }
    if (draftIsDirty || draftMutationInProgress) { message.textContent = "请先保存编辑内容，再评价此版本。"; return; }
    const runId = selectedRun, versionId = selectedVersion;
    const button = byId("result-feedback-submit"); button.disabled = true;
    try {
      const saved = await request(runId, "/feedback", { version_id: versionId, scope: "result", rating, reason: byId("result-feedback-reason").value });
      if (runId !== selectedRun || versionId !== selectedVersion) return;
      feedback = feedback.filter(item => item.id !== saved.id).concat(saved);
      message.textContent = "评价已保存，感谢提供反馈。";
      window.refreshQualityDashboard();
    } catch (error) { if (runId === selectedRun) message.textContent = error.message; }
    finally { button.disabled = false; }
  });

  window.buildChangeFeedback = function(item, versionId, runId) {
    const details = document.createElement("details"); details.className = "change-feedback";
    const summary = document.createElement("summary"); summary.textContent = "评价这条修改"; details.append(summary);
    const message = document.createElement("p"); message.className = "review-help";
    if (!versionId) { message.textContent = "请保存当前草稿并刷新对比后，再评价此条修改。"; details.append(message); return details; }
    const rating = document.createElement("select"); rating.setAttribute("aria-label", `${item.label} 修改评分`);
    rating.append(new Option("请选择评分", ""));
    for (let number = 5; number >= 1; number--) rating.append(new Option(`${number} 分`, String(number)));
    const reason = document.createElement("select"); reason.setAttribute("aria-label", `${item.label} 反馈原因`);
    for (const [value, text] of Object.entries(reasonNames)) reason.append(new Option(text, value));
    const saved = feedback.find(entry => entry.scope === "change" && entry.version_id === versionId && entry.target_id === item.id);
    if (saved) { rating.value = String(saved.rating); reason.value = saved.reason; message.textContent = "此条修改已有评价，可以更新。"; }
    details.addEventListener("toggle", () => {
      if (!details.open || rating.value) return;
      const restored = feedback.find(entry => entry.scope === "change" && entry.version_id === versionId && entry.target_id === item.id);
      if (restored) { rating.value = String(restored.rating); reason.value = restored.reason; message.textContent = "此条修改已有评价，可以更新。"; }
    });
    const button = document.createElement("button"); button.type = "button"; button.className = "secondary-button"; button.textContent = "保存此条评价";
    button.addEventListener("click", async () => {
      if (!rating.value) { message.textContent = "请选择评分。"; return; }
      button.disabled = true;
      try {
        const record = await request(runId, "/feedback", { version_id: versionId, scope: "change", target_id: item.id, rating: Number(rating.value), reason: reason.value });
        feedback = feedback.filter(entry => entry.id !== record.id).concat(record);
        message.textContent = "此条修改的评价已保存。"; window.refreshQualityDashboard();
      } catch (error) { message.textContent = error.message; }
      finally { button.disabled = false; }
    });
    details.append(rating, reason, button, message);
    return details;
  };

  window.recordQualityDecision = async function(runId, versionId, targetId, decision) {
    if (!versionId) return;
    try {
      await request(runId, "/change-decisions", { version_id: versionId, target_id: targetId, decision, event_id: crypto.randomUUID() });
      window.refreshQualityDashboard();
    } catch (error) { byId("result-feedback-status").textContent = `本地修改已应用，但决策记录未保存：${error.message}`; }
  };

  function table(title, groups, labels = {}) {
    const section = document.createElement("section");
    const heading = document.createElement("h4"); heading.textContent = title;
    const table = document.createElement("table");
    const head = document.createElement("tr");
    for (const name of ["分组", "完成任务", "平均评分", "导出率"]) { const cell = document.createElement("th"); cell.textContent = name; head.append(cell); }
    table.append(head);
    for (const group of groups) {
      const row = document.createElement("tr");
      const values = [labels[group.key] || group.key.slice(0, 14), group.metrics.completed_runs, group.metrics.average_rating ?? "暂无", percent(group.metrics.export_rate)];
      for (const value of values) { const cell = document.createElement("td"); cell.textContent = value; row.append(cell); }
      table.append(row);
    }
    section.append(heading, table); return section;
  }

  window.refreshQualityDashboard = async function() {
    const sequence = ++dashboardSequence;
    try {
      const response = await fetch("/api/v1/quality/dashboard", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
        runs: typeof rememberedHistoryRuns === "function" ? rememberedHistoryRuns().map(({id, token}) => ({id, token})) : [],
        archives: archiveCredentials.map(({id, token}) => ({id, token})),
        hiring_track: byId("quality-track").value, language: byId("quality-language").value,
      }) });
      const result = await response.json();
      if (sequence !== dashboardSequence) return;
      if (!response.ok) throw new Error("质量概览暂时不可用，请稍后刷新。");
      const metrics = result.metrics;
      const funnel = byId("quality-funnel"); funnel.replaceChildren();
      for (const [label, key] of [["已开始", "started_runs"], ["已完成", "completed_runs"], ["主动审阅", "reviewed_runs"], ["保存编辑", "edited_runs"], ["成功导出", "exported_runs"]]) {
        const cell = document.createElement("div"); const number = document.createElement("strong"); number.textContent = metrics[key];
        const text = document.createElement("span"); text.textContent = label; cell.append(number, text); funnel.append(cell);
      }
      byId("quality-summary").textContent = `整份评价 ${metrics.feedback_count} 份 · 平均评分 ${metrics.average_rating ?? "暂无数据"} · 满意率 ${percent(metrics.satisfaction_rate)} · 修改评价 ${metrics.change_feedback_count} 份 / 均分 ${metrics.average_change_rating ?? "暂无数据"} · 主动接受修改 ${metrics.accepted_changes} 项 / 拒绝 ${metrics.rejected_changes} 项 · 接受率 ${percent(metrics.change_acceptance_rate)} · 导出率 ${percent(metrics.export_rate)}`;
      byId("quality-status").textContent = result.disclaimer;
      const labels = Object.fromEntries(result.provenance.map(item => [item.fingerprint, `${item.model} / ${item.prompt_version} / ${item.fingerprint.slice(0, 8)}`]));
      byId("quality-breakdown").replaceChildren(table("招聘类型", result.by_hiring_track, {campus:"校招",intern:"实习",experienced:"社招",unknown:"未识别"}),
        table("输出语言", result.by_language, {zh:"中文",en:"英文",unknown:"未识别"}),
        table("生成版本", result.by_generation_version, labels), table("每日趋势（北京时间）", result.daily_trend));
    } catch (error) { if (sequence === dashboardSequence) byId("quality-status").textContent = error.message; }
  };

  byId("quality-refresh").addEventListener("click", window.refreshQualityDashboard);
  byId("quality-track").addEventListener("change", window.refreshQualityDashboard);
  byId("quality-language").addEventListener("change", window.refreshQualityDashboard);
  window.refreshQualityDashboard();
})();
