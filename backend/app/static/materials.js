(() => {
  const el = id => document.getElementById(id), buffers = new Map(), dirtyBuffers = new Set();
  let context = null, pack = null, documentId = "", epoch = 0, listSequence = 0, busy = false;
  const message = text => { el("materials-status").textContent = text; };
  const doc = () => pack?.documents.find(item => item.id === documentId);
  const key = () => pack ? `${pack.run_id}:${pack.id}:${documentId}` : "";
  const dirty = () => !!doc() && (el("materials-content").value !== doc().content || el("materials-reviewed").checked !== doc().reviewed);
  const stash = () => {
    if (!doc()) return;
    buffers.set(key(), {content:el("materials-content").value, reviewed:el("materials-reviewed").checked});
    if (dirty()) dirtyBuffers.add(key()); else dirtyBuffers.delete(key());
  };
  const pending = () => pack?.documents.some(item => {
    const buffer = buffers.get(`${pack.run_id}:${pack.id}:${item.id}`);
    return buffer && (buffer.content !== item.content || buffer.reviewed !== item.reviewed);
  });
  function controls() {
    document.querySelectorAll(".materials-panel button, .materials-panel select, .materials-panel textarea, .materials-panel input").forEach(item => { item.disabled = busy; });
    for (const id of ["materials-document", "materials-delete", "materials-save", "materials-discard"]) el(id).disabled = busy || !pack;
    el("materials-generate").disabled = busy || !context?.versionId;
    el("materials-download").disabled = busy || !doc()?.reviewed || dirty();
    el("materials-download-pack").disabled = busy || !pack || pack.documents.some(item => !item.reviewed) || pending() || dirty();
  }
  async function api(path = "", options = {}, scope = context) {
    const response = await fetch(`/api/v1/tailor-runs/${scope.runId}/materials${path}`, {...options,
      headers:{"Content-Type":"application/json", "X-Run-Token":scope.token}});
    if (!response.ok) throw new Error(await getResponseError(response, "材料包请求失败。"));
    return response;
  }
  async function operate(action) {
    if (busy || !context) return;
    const sequence = epoch, scope = context; busy = true; controls();
    try { await action(scope, sequence); }
    catch (error) { if (sequence === epoch) message(error.message); }
    finally { if (sequence === epoch) { busy = false; controls(); } }
  }
  function renderDocument() {
    const item = doc();
    if (!item) return;
    const buffer = buffers.get(key());
    el("materials-content").value = buffer?.content ?? item.content;
    el("materials-reviewed").checked = buffer?.reviewed ?? item.reviewed;
    el("materials-length").textContent = `${item.length_hint} 正文 ${el("materials-content").value.length} 字符。`;
    el("materials-issues").replaceChildren();
    for (const issue of item.issues) {
      const li = document.createElement("li"); li.textContent = `${issue.quote ? `「${issue.quote}」：` : ""}${issue.reason}`; el("materials-issues").append(li);
    }
    const evidence = pack.evidence.filter(value => item.evidence_ids.includes(value.id));
    el("materials-source").textContent = [`目标公司：${pack.company || "未提供"} · 岗位：${pack.role}`, `来源 JD：\n${pack.jd_text || JSON.stringify(pack.jd_profile,null,2)}`,
      ...pack.notes, ...evidence.map(value => `事实 [${value.fact_ids.join(", ")}]：${value.text}\n简历位置 ${value.resume_span}：${value.resume_text}`),
      item.edited ? "已手工编辑：原引用不自动证明新增表达。规则检查覆盖有限。" : "经历原句来自同一组已确认事实。"].join("\n\n");
    controls();
  }
  function render(value) {
    pack = value;
    if (!pack.documents.some(item => item.id === documentId)) documentId = pack.documents[0].id;
    el("materials-document").replaceChildren();
    for (const item of pack.documents) el("materials-document").add(new Option(`${item.title}${item.reviewed ? " · 已核对" : " · 待核对"}`,item.id));
    el("materials-document").value = documentId;
    el("materials-editor").classList.remove("hidden");
    el("materials-context").textContent = `来源简历：${pack.version_label} · ${pack.version_id.slice(0,8)} · 修订 ${pack.revision} · 保存至 ${new Date(pack.expires_at).toLocaleString()}${pack.version_id !== context.versionId ? "。当前简历已切换，这套材料仍保留原版本。" : ""}`;
    renderDocument();
  }
  async function list(scope, sequence, selected = pack?.id || "") {
    const request = ++listSequence;
    const items = await (await api("", {}, scope)).json();
    if (sequence !== epoch || request !== listSequence) return;
    el("materials-packs").replaceChildren(new Option("选择材料包", ""));
    for (const item of items) el("materials-packs").add(new Option(`${item.version_label} · ${new Date(item.created_at).toLocaleString()} · 已核对 ${item.reviewed_count}/${item.document_count}`,item.id));
    if (items.some(item => item.id === selected)) el("materials-packs").value = selected;
  }
  window.initializeMaterials = async (runId, versionId) => {
    stash(); epoch += 1; const sequence = epoch, previous = context;
    context = {runId, versionId, token:currentRunToken}; busy = false;
    if (previous?.runId !== runId) {
      pack = null; documentId = ""; el("materials-editor").classList.add("hidden");
      el("materials-context").textContent = ""; el("materials-document").replaceChildren();
    } else if (pack) render(pack);
    controls(); message("保存简历后生成材料包；未保存的材料文字暂存在本页，刷新网页前请保存。");
    try { await list(context, sequence); } catch (error) { if (sequence === epoch) message(error.message); }
  };
  el("materials-content").addEventListener("input", () => {
    el("materials-reviewed").checked = false; stash(); controls();
    el("materials-length").textContent = `${doc()?.length_hint || ""} 正文 ${el("materials-content").value.length} 字符。`;
    message("材料已修改。保存后重新检查风险；新增经历需先在事实库确认。原引用不证明新增文字。");
  });
  el("materials-reviewed").addEventListener("change", () => { stash(); controls(); });
  el("materials-document").addEventListener("change", () => { stash(); documentId = el("materials-document").value; renderDocument(); message("已切换材料；本页未保存文字仍保留。下载前请保存并核对。"); });
  el("materials-generate").addEventListener("click", () => operate(async (scope, sequence) => {
    if (draftIsDirty || draftMutationInProgress) throw new Error("请先保存当前简历编辑，再生成材料包。");
    stash(); message("正在根据已保存版本与 JD 选择事实并准备材料…");
    const value = await (await api("", {method:"POST",body:JSON.stringify({version_id:scope.versionId})},scope)).json();
    if (sequence !== epoch) return;
    documentId = ""; render(value); await list(scope,sequence,value.id); message("材料包已生成。请逐份核对、补充占位内容并保存，再导出。");
  }));
  el("materials-packs").addEventListener("change", () => operate(async (scope, sequence) => {
    stash(); const id = el("materials-packs").value;
    if (!id) { pack = null; el("materials-editor").classList.add("hidden"); el("materials-context").textContent=""; return; }
    const value = await (await api(`/${id}`, {},scope)).json(); if (sequence === epoch) { documentId=""; render(value); message("已载入材料包。本页未保存文字会保留；下载前请保存。"); }
  }));
  el("materials-refresh").addEventListener("click", () => operate(async (scope, sequence) => {
    stash(); if (pack) { const value = await (await api(`/${pack.id}`, {},scope)).json(); if (sequence === epoch) render(value); }
    await list(scope,sequence); if (sequence === epoch) message("已载入最新修订，未保存文字保留在本页。核对后再保存可避免并发覆盖。");
  }));
  el("materials-save").addEventListener("click", () => operate(async (scope, sequence) => {
    if (!pack || !doc()) return;
    const id = documentId, savedKey = key(); stash();
    const value = await (await api(`/${pack.id}/documents/${id}`, {method:"PUT",body:JSON.stringify({expected_revision:pack.revision,
      content:el("materials-content").value,reviewed:el("materials-reviewed").checked})},scope)).json();
    buffers.delete(savedKey); dirtyBuffers.delete(savedKey); if (sequence !== epoch) return;
    render(value); await list(scope,sequence); message("材料已保存。请查看事实与占位内容提示；手工修改需要本人核实。");
  }));
  el("materials-discard").addEventListener("click", () => { buffers.delete(key()); dirtyBuffers.delete(key()); renderDocument(); message("已恢复这份材料最后保存的内容与核对状态。"); });
  async function download(path, filename, scope) {
    const response = await api(path,{},scope), blob = await response.blob(), url = URL.createObjectURL(blob);
    const link = document.createElement("a"); link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url),1000);
  }
  el("materials-download").addEventListener("click", () => operate(async scope => {
    if (dirty()) throw new Error("请先保存材料编辑。");
    await download(`/${pack.id}/documents/${documentId}/export`,`${documentId}.md`,scope);
  }));
  el("materials-download-pack").addEventListener("click", () => operate(async scope => {
    if (pending() || dirty()) throw new Error("请先保存所有材料编辑。");
    await download(`/${pack.id}/export`,"application-materials.zip",scope);
  }));
  el("materials-delete").addEventListener("click", () => operate(async (scope, sequence) => {
    if (!pack || !window.confirm("删除这套材料包及未保存的本页编辑？源简历和事实仍保留。")) return;
    const prefix = `${pack.run_id}:${pack.id}:`;
    await api(`/${pack.id}`,{method:"DELETE"},scope);
    for (const value of buffers.keys()) if (value.startsWith(prefix)) { buffers.delete(value); dirtyBuffers.delete(value); }
    if (sequence !== epoch) return;
    pack = null; documentId = ""; el("materials-editor").classList.add("hidden"); el("materials-context").textContent="";
    await list(scope,sequence,""); message("材料包已删除。");
  }));
  window.addEventListener("beforeunload", event => {
    stash();
    if (dirtyBuffers.size) { event.preventDefault(); event.returnValue=""; }
  });
  if (currentRunId && activeVersionId && currentDraft) window.initializeMaterials(currentRunId,activeVersionId);
})();
