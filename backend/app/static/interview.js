(() => {
  const el = id => document.getElementById(id);
  const buffers = new Map(), labels = {active: "进行中", completed: "已完成", stopped: "提前结束"};
  let context = null, current = null, busy = false, epoch = 0, listSequence = 0;
  const message = text => { el("interview-status").textContent = text; };
  const key = () => current?.current_question ? `${context.runId}:${current.session.id}:${current.current_question.id}` : "";
  const paragraph = text => { const p = document.createElement("p"); p.textContent = text; return p; };

  function controls() {
    document.querySelectorAll(".mock-interview-panel button, .mock-interview-panel select, .mock-interview-panel textarea").forEach(control => { control.disabled = busy; });
    el("interview-finish").disabled = busy || !current || current.session.status !== "active";
    el("interview-delete").disabled = busy || !current;
    el("interview-download").disabled = busy || !current?.session.turns.length;
    el("interview-submit").disabled = busy || !current?.current_question;
    el("interview-start").disabled = busy || !context?.versionId;
  }
  async function api(path = "", options = {}, scope = context) {
    const response = await fetch(`/api/v1/tailor-runs/${scope.runId}/interviews${path}`, {...options,
      headers: {"Content-Type": "application/json", "X-Run-Token": scope.token}});
    if (!response.ok) throw new Error(await getResponseError(response, "面试练习请求失败。"));
    return response;
  }
  async function operate(action) {
    if (busy || !context) return;
    const sequence = epoch, scope = context; busy = true; controls();
    try { await action(scope, sequence); }
    catch (error) { if (sequence === epoch) message(error.message); }
    finally { if (sequence === epoch) { busy = false; controls(); } }
  }
  function clear() {
    current = null; el("interview-question-panel").classList.add("hidden");
    el("interview-feedback").replaceChildren(); el("interview-report-panel").classList.add("hidden");
    el("interview-context").textContent = ""; el("interview-answer").value = "";
  }
  function render(view) {
    current = view;
    const session = view.session, question = view.current_question;
    el("interview-context").textContent = `练习版本：${session.version_label} · ${session.version_id.slice(0,8)} · ${labels[session.status]} · 已回答 ${session.turns.length} / 当前共 ${session.questions.length} 题（每轮最多一次追问） · 保存至 ${new Date(session.expires_at).toLocaleString()}${session.version_id !== context.versionId ? "。此练习使用之前的版本快照。" : ""}`;
    el("interview-question-panel").classList.toggle("hidden", !question);
    if (question) {
      el("interview-question-number").textContent = `第 ${question.round_number} / ${session.rounds} 轮${question.kind === "follow_up" ? " · 追问" : ""}`;
      el("interview-question").textContent = question.prompt;
      el("interview-jd-reference").textContent = `JD：${question.jd_reference}`;
      el("interview-resume-reference").textContent = `简历：${question.resume_reference}`;
      el("interview-facts").replaceChildren();
      for (const factId of question.fact_ids) {
        const fact = session.fact_cards.find(item => item.id === factId);
        if (fact) { const li = document.createElement("li"); li.textContent = `已确认事实：${fact.text}`; el("interview-facts").append(li); }
      }
      el("interview-answer").value = buffers.get(key()) || "";
    } else el("interview-answer").value = "";
    const root = el("interview-feedback"); root.replaceChildren();
    const latest = session.turns.at(-1);
    if (latest) {
      root.append(paragraph(`上一题反馈 · ${latest.feedback.method === "model" ? "模型评估" : "规则评估（有限事实检查）"}。评分用于练习，不代表通过率或事实认证。`));
      for (const [name, label] of Object.entries({structure:"结构", evidence:"证据", clarity:"清晰度", consistency:"一致性"})) {
        const item = latest.feedback[name], card = document.createElement("div"); card.className = "interview-assessment";
        const title = document.createElement("strong"); title.textContent = `${label} ${item.score} / 4`;
        card.append(title, paragraph(item.reason)); if (item.answer_quote) card.append(paragraph(`回答片段：「${item.answer_quote}」`)); root.append(card);
      }
      for (const issue of latest.feedback.issues) {
        const card = document.createElement("div"); card.className = "interview-issue";
        const kind = {inconsistent:"可能不一致", unverified:"需要核实", expression:"表达建议"}[issue.kind];
        card.append(paragraph(`${kind}：「${issue.answer_quote}」`), paragraph(issue.explanation), paragraph(issue.recommendation));
        for (const id of issue.fact_ids) {
          const fact = session.fact_cards.find(item => item.id === id); if (fact) card.append(paragraph(`对照事实：${fact.text}`));
        }
        root.append(card);
      }
      const list = document.createElement("ul");
      for (const suggestion of latest.feedback.suggestions) { const li = document.createElement("li"); li.textContent = suggestion; list.append(li); }
      root.append(list);
    }
    el("interview-report").textContent = view.report; el("interview-report-panel").classList.toggle("hidden", !session.turns.length); controls();
  }
  async function list(scope, sequence, selected = current?.session.id || "") {
    const requestSequence = ++listSequence;
    const sessions = await (await api("", {}, scope)).json(); if (sequence !== epoch || requestSequence !== listSequence) return;
    const select = el("interview-sessions"); select.replaceChildren(new Option("选择练习", ""));
    for (const item of sessions) select.add(new Option(`${new Date(item.created_at).toLocaleString()} · ${item.version_label} · ${labels[item.status]} · ${item.answered_count} 题`, item.id));
    if (sessions.some(item => item.id === selected)) select.value = selected;
  }
  window.initializeInterviewPractice = async (runId, versionId) => {
    const sameRun = context?.runId === runId; epoch += 1; const sequence = epoch;
    context = {runId, versionId, token: currentRunToken}; busy = false;
    if (!sameRun) clear(); else if (current) render(current);
    controls(); message("先保存简历编辑，再用该版本开始练习；已保存的练习可以恢复或重复练习。");
    try { await list(context, sequence); } catch (error) { if (sequence === epoch) message(error.message); }
  };
  el("interview-answer").addEventListener("input", () => { if (key()) buffers.set(key(), el("interview-answer").value); });
  el("interview-start").addEventListener("click", () => operate(async (scope, sequence) => {
    if (draftIsDirty || draftMutationInProgress) throw new Error("请先保存当前简历编辑，再开始新练习。");
    message("正在准备基于当前简历和 JD 的问题…");
    const view = await (await api("", {method:"POST", body:JSON.stringify({version_id:scope.versionId, rounds:Number(el("interview-rounds").value)})}, scope)).json();
    if (sequence !== epoch) return; render(view); await list(scope, sequence, view.session.id); message("练习已开始。请按真实经历作答，不确定的信息可以直接说明。");
  }));
  el("interview-sessions").addEventListener("change", () => operate(async (scope, sequence) => {
    const id = el("interview-sessions").value; if (!id) { clear(); message("请选择已保存的练习，或开始新练习。"); return; }
    const view = await (await api(`/${id}`, {}, scope)).json(); if (sequence === epoch) { render(view); message("已恢复练习。已提交回答和反馈保存在报告中。"); }
  }));
  el("interview-refresh").addEventListener("click", () => operate(async (scope, sequence) => {
    if (current) { const view = await (await api(`/${current.session.id}`, {}, scope)).json(); if (sequence === epoch) render(view); }
    await list(scope, sequence); if (sequence === epoch) message("练习已刷新；未提交文字按题保留在本页，刷新网页后不会保留。");
  }));
  el("interview-submit").addEventListener("click", () => operate(async (scope, sequence) => {
    if (!current?.current_question) return;
    const answer = el("interview-answer").value.trim(); if (!answer) throw new Error("请填写回答后再提交。");
    const answerKey = key(), session = current.session; message("正在评估回答并准备下一题…");
    const view = await (await api(`/${session.id}/answers`, {method:"POST", body:JSON.stringify({question_id:current.current_question.id, expected_revision:session.revision, answer})}, scope)).json();
    buffers.delete(answerKey); if (sequence !== epoch) return;
    render(view); await list(scope, sequence, view.session.id); message(view.session.status === "completed" ? "练习已完成。可复习全部回答和改进建议，或开始新的练习。" : "回答已保存。先检查反馈，再回答下一题。");
  }));
  el("interview-finish").addEventListener("click", () => operate(async (scope, sequence) => {
    const session = current.session;
    const view = await (await api(`/${session.id}/finish`, {method:"POST", body:JSON.stringify({expected_revision:session.revision})}, scope)).json();
    if (sequence !== epoch) return; render(view); await list(scope, sequence, session.id); message("练习已提前结束。报告保留已提交回答；未提交内容未写入报告。");
  }));
  el("interview-delete").addEventListener("click", () => operate(async (scope, sequence) => {
    const id = current.session.id; await api(`/${id}`, {method:"DELETE"}, scope);
    for (const savedKey of buffers.keys()) if (savedKey.startsWith(`${scope.runId}:${id}:`)) buffers.delete(savedKey);
    if (sequence !== epoch) return; clear(); await list(scope, sequence, ""); message("所选练习已删除，可以开始新练习。");
  }));
  el("interview-download").addEventListener("click", () => operate(async (scope, sequence) => {
    const blob = await (await api(`/${current.session.id}/report`, {}, scope)).blob(); if (sequence !== epoch) return;
    const url = URL.createObjectURL(blob), link = document.createElement("a"); link.href = url; link.download = "面试复习报告.md"; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000); message("复习报告已下载。");
  }));
  if (currentRunId && activeVersionId && currentDraft) window.initializeInterviewPractice(currentRunId, activeVersionId);
})();
