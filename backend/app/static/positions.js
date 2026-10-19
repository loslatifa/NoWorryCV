(() => {
  const el = id => document.getElementById(id);
  const stages = {pending:"待投递", applied:"已投递", assessment:"笔试", interview:"面试", offer:"Offer", closed:"关闭"};
  let credentials = [], profile = null, archive = null, position = null, busy = false, dirty = false, sequence = 0;
  let sourceData = {runs:[], applications:[]}, versions = [], preview = null, practices = [], materialPacks = [], listSequence = 0;
  const message = text => { el("board-status").textContent = text; };
  const paragraph = text => { const p = document.createElement("p"); p.textContent = text; return p; };
  function controls() {
    document.querySelectorAll("button, input, textarea, select").forEach(element => { element.disabled = busy || (!profile && element.id !== "board-profile"); });
  }
  function clean() { if (dirty) throw new Error("当前职位有未保存编辑，请先保存，或点击放弃修改并重载。"); }
  async function api(path = "", options = {}, scope = profile, direct = false) {
    if (!scope) throw new Error("请先在简历工作台保存并选择基础档案。");
    const url = direct ? path : `/api/v1/candidate-profiles/${scope.id}/positions${path}`;
    const response = await fetch(url, {...options, headers:{"Content-Type":"application/json", "X-Profile-Token":scope.token, ...(options.headers || {})}});
    if (!response.ok) {
      let data; try { data = await response.json(); } catch (_) { data = {}; }
      throw new Error(typeof data.detail === "string" ? data.detail : "请求未完成，请检查输入并重试。");
    }
    return response;
  }
  async function act(action) {
    if (busy) return; const scope = profile, epoch = sequence; busy = true; controls();
    try { await action(scope, epoch); }
    catch (error) { if (epoch === sequence) message(error.message); }
    finally { if (epoch === sequence) { busy = false; controls(); } }
  }
  function button(text, action, className="secondary-button") {
    const button = document.createElement("button"); button.type="button"; button.className=className; button.textContent=text;
    button.addEventListener("click", () => act(action)); return button;
  }
  function details(title, text) {
    const detail = document.createElement("details"), summary = document.createElement("summary"), pre = document.createElement("pre");
    summary.textContent=title; pre.textContent=text; detail.append(summary,pre); return detail;
  }
  function localDate(value) {
    if (!value) return ""; const date = new Date(value);
    return new Date(date.getTime() - date.getTimezoneOffset()*60000).toISOString().slice(0,16);
  }
  async function download(path, filename) {
    const blob = await (await api(path)).blob(), url = URL.createObjectURL(blob), anchor = document.createElement("a");
    anchor.href=url; anchor.download=filename; anchor.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  function taskLink(runId, label) {
    const link=document.createElement("a"); link.href=`/app/?run=${encodeURIComponent(runId)}&profile=${encodeURIComponent(profile.id)}`;
    link.target="_blank"; link.rel="noopener"; link.textContent=label; link.className="secondary-button"; return link;
  }
  async function loadList(scope=profile) {
    if (!scope) return; const request=++listSequence, epoch=sequence;
    const query=new URLSearchParams({search:el("board-search").value, status:el("board-stage").value, reminder:el("board-reminder").value});
    const data=await (await api(`?${query}`, {}, scope)).json(); if (epoch!==sequence || request!==listSequence) return;
    el("board-counts").replaceChildren();
    for (const [status,label] of Object.entries(stages)) el("board-counts").append(button(`${label} ${data.counts[status]}`, async()=>{ el("board-stage").value=status; await loadList(); }));
    el("board-list").replaceChildren();
    for (const item of data.items) {
      const row=button(`${item.company} · ${item.role}`, async()=>{ clean(); await loadPosition(item.id); }, `board-job${position?.id===item.id ? " active" : ""}`);
      row.append(paragraph(`${stages[item.status]} · ${item.current_resume_label || "尚未关联简历"}`));
      if (item.next_action) row.append(paragraph(`下一步：${item.next_action}`));
      if (item.reminder!=="none") { const reminder=paragraph(`${item.reminder==="due" ? "提醒已到期" : "待提醒"}：${new Date(item.remind_at).toLocaleString()}`); reminder.className=item.reminder; row.append(reminder); }
      el("board-list").append(row);
    }
    if (!data.items.length) el("board-list").append(paragraph("当前筛选下没有职位，可新增职位或调整筛选。"));
  }
  async function loadSources() {
    sourceData=await (await api("/sources")).json();
    const select=el("material-source"); select.replaceChildren(new Option("请选择", ""));
    for (const run of sourceData.runs) {
      const option=new Option(`生成任务 · ${run.company || "未填写公司"} · ${run.role || "定制简历"} · ${run.status==="completed" ? "可选版本" : "尚未完成"}`, `run:${run.run_id}`);
      option.disabled=run.status!=="completed"; select.add(option);
    }
    for (const application of sourceData.applications) select.add(new Option(`已确认投递 · ${application.company} · ${application.role}`, `application:${application.id}`));
    preview=null; versions=[]; el("material-version").replaceChildren(); el("material-preview").textContent="请选择来源，并核对实际简历。"; el("material-consent").checked=false;
  }
  function rememberedRuns() {
    try { const saved=JSON.parse(localStorage.getItem("noworrycv-run-history") || "[]"); return Array.isArray(saved) ? saved.filter(item=>item.id && item.token) : []; }
    catch(_) { return []; }
  }
  async function loadPractices() {
    const remembered=rememberedRuns().filter(item=>position.resumes.some(resume=>resume.run_id===item.id));
    practices=await (await api(`/${position.id}/practice-sources`,{method:"POST",body:JSON.stringify({runs:remembered.map(item=>({id:item.id,token:item.token}))})})).json();
    el("practice-source").replaceChildren(new Option("请选择；原任务到期前可保存练习报告", ""));
    practices.forEach((item,index)=>el("practice-source").add(new Option(`${item.resume_label} · ${item.session.answered_count} 题 · ${new Date(item.session.created_at).toLocaleString()}`, String(index))));
    el("practice-consent").checked=false;
    materialPacks=await (await api(`/${position.id}/material-sources`,{method:"POST",body:JSON.stringify({runs:remembered.map(item=>({id:item.id,token:item.token}))})})).json();
    el("pack-source").replaceChildren(new Option("请选择材料包", ""));
    materialPacks.forEach((item,index)=>el("pack-source").add(new Option(`${item.resume_label} · 修订 ${item.pack.revision} · 已核对 ${item.pack.reviewed_count}/${item.pack.document_count}`,String(index))));
    el("pack-preview").textContent=""; el("pack-consent").checked=false;
  }
  function renderPosition(item) {
    position=item; dirty=false; el("board-detail").classList.remove("hidden");
    el("position-heading").textContent=`${item.company} · ${item.role}`;
    const current=item.resumes.find(resume=>resume.id===item.current_resume_id);
    el("position-current").textContent=`${stages[item.status]} · 当前投递版本：${current ? current.label : "未关联"} · ${item.resumes.length} 份简历 / ${item.interviews.length} 份面试报告`;
    for (const [field,id] of Object.entries({company:"edit-company",role:"edit-role",jd_text:"edit-jd",job_url:"edit-url",status:"edit-stage",next_action:"edit-action"})) el(id).value=item[field];
    el("edit-remind").value=localDate(item.remind_at); el("edit-note").value="";
    el("position-runs").replaceChildren();
    for (const run of item.runs) el("position-runs").append(taskLink(run.run_id, `查看生成任务 · ${new Date(run.created_at).toLocaleString()}`));
    el("position-resumes").replaceChildren();
    for (const resume of [...item.resumes].reverse()) {
      const card=document.createElement("article"); card.className=`board-material${resume.id===item.current_resume_id ? " current" : ""}`;
      const h=document.createElement("h4"); h.textContent=`${resume.label}${resume.id===item.current_resume_id ? " · 当前投递版本" : ""}`; card.append(h,paragraph(`保存于 ${new Date(resume.captured_at).toLocaleString()} · ${resume.source_kind==="application" ? "已确认投递快照" : "已保存简历版本"}`));
      if (resume.jd_text.trim()!==item.jd_text.trim() || resume.source_company && resume.source_company!==item.company || resume.source_role && resume.source_role!==item.role) card.append(paragraph("来源岗位或 JD 与当前职位不同，请对照核实；此材料保留原来源。"));
      card.append(details("简历与来源 JD", `来源岗位：${resume.source_company} · ${resume.source_role}\n来源 JD：\n${resume.jd_text}\n\n${resume.draft.markdown || JSON.stringify(resume.draft,null,2)}`));
      if (resume.risk_notes.length) card.append(details("需要复核",resume.risk_notes.join("\n")));
      if (resume.jd_review) card.append(details("JD 复习文档",resume.jd_review));
      if (resume.interview_prep) card.append(details("面试准备文档",resume.interview_prep));
      const actions=document.createElement("div"); actions.className="archive-actions";
      if (resume.id!==item.current_resume_id) actions.append(button("设为当前投递版本",async()=>{ clean(); await update(await (await api(`/${item.id}/resumes/${resume.id}/current`,{method:"POST",body:JSON.stringify({expected_revision:position.revision})})).json()); }));
      for (const format of ["pdf","docx"]) actions.append(button(`下载 ${format.toUpperCase()}`,()=>download(`/${item.id}/resumes/${resume.id}/${format}`,`${item.company}-${item.role}.${format}`)));
      if (resume.source_profile_id===profile.id) actions.append(taskLink(resume.run_id,"打开源任务 / 面试练习（保存期内）"));
      card.append(actions); el("position-resumes").append(card);
    }
    el("position-interviews").replaceChildren();
    for (const report of [...item.interviews].reverse()) {
      const card=document.createElement("article"); card.className="board-material";
      const resume=item.resumes.find(resume=>resume.id===report.resume_id);
      card.append(paragraph(`${resume?.label || "来源简历"} · ${report.answered_count} 题 · 保存于 ${new Date(report.captured_at).toLocaleString()}`),details("查看面试复习报告",report.report),button("下载面试复习报告",()=>download(`/${item.id}/interviews/${report.id}/report`,"职位面试复习报告.md")));
      el("position-interviews").append(card);
    }
    el("position-timeline").replaceChildren();
    el("position-material-packs").replaceChildren();
    for(const saved of [...item.materials].reverse()) {
      const card=document.createElement("article"); card.className="board-material";
      card.append(paragraph(`${saved.pack.version_label} · 修订 ${saved.pack.revision} · 长期保存于 ${new Date(saved.captured_at).toLocaleString()}`));
      card.append(details("材料与来源 JD",`${saved.pack.company} · ${saved.pack.role}\n来源 JD：\n${saved.pack.jd_text}\n\n${saved.pack.documents.map(doc=>`${doc.title}\n${doc.content}`).join("\n\n")}`));
      if(saved.pack.company!==item.company || saved.pack.role!==item.role || saved.pack.jd_text.trim()!==item.jd_text.trim()) card.append(paragraph("这套材料保留原目标 JD，请与当前职位核对。"));
      card.append(button("下载求职材料包 ZIP",()=>download(`/${item.id}/materials/${saved.id}/export`,"position-materials.zip"))); el("position-material-packs").append(card);
    }
    const names={company:"公司",role:"职位",jd_text:"JD",job_url:"岗位链接",status:"阶段",next_action:"下一步",remind_at:"提醒时间"};
    for (const event of [...item.timeline].reverse()) {
      const card=document.createElement("article"); card.className="board-event"; card.append(paragraph(`${new Date(event.at).toLocaleString()} · ${event.summary}`));
      if (event.note) card.append(paragraph(event.note));
      if (Object.keys(event.changes).length) card.append(details("查看变化",Object.entries(event.changes).map(([key,values])=>`${names[key] || key}：${key==="status" ? stages[values[0]] : values[0] || "空"} → ${key==="status" ? stages[values[1]] : values[1] || "空"}`).join("\n")));
      el("position-timeline").append(card);
    }
  }
  async function loadPosition(id) {
    renderPosition(await (await api(`/${id}`)).json()); await loadSources(); await loadPractices(); await loadList();
  }
  async function update(item) { renderPosition(item); await loadPractices(); await loadList(); }

  el("board-profile").addEventListener("change",()=>act(async()=>{
    if (dirty) { el("board-profile").value=profile.id; throw new Error("请先保存职位修改，或放弃修改并重载。"); }
    sequence++; const epoch=sequence; profile=credentials.find(item=>item.id===el("board-profile").value) || null; position=null; archive=null;
    el("board-detail").classList.add("hidden"); el("board-list").replaceChildren(); el("board-counts").replaceChildren();
    if (!profile) { message("请在简历工作台保存基础档案，再使用职位工作台。"); busy=false; controls(); return; }
    try { archive=await (await api(`/api/v1/candidate-profiles/${profile.id}`,{},profile,true)).json(); await loadList(); message("已载入职位，保存的材料保留至主动删除。"); }
    catch(error) { if(epoch===sequence) { message(error.message); profile=null; archive=null; } }
    finally { if(epoch===sequence) { busy=false; controls(); } }
  }));
  el("board-create").addEventListener("submit",event=>{event.preventDefault();act(async()=>{
    clean(); const item=await (await api("",{method:"POST",body:JSON.stringify({company:el("new-company").value,role:el("new-role").value,jd_text:el("new-jd").value,job_url:el("new-url").value || null,storage_consent:el("new-consent").checked})})).json();
    el("board-create").reset(); await loadPosition(item.id); message("职位已保存，当前阶段为待投递。");
  });});
  el("position-edit").addEventListener("input",()=>{dirty=true;});
  el("position-edit").addEventListener("submit",event=>{event.preventDefault();act(async()=>{
    const reminder=el("edit-remind").value;
    const item=await (await api(`/${position.id}`,{method:"PATCH",body:JSON.stringify({expected_revision:position.revision,company:el("edit-company").value,role:el("edit-role").value,jd_text:el("edit-jd").value,job_url:el("edit-url").value || null,status:el("edit-stage").value,next_action:el("edit-action").value,remind_at:reminder ? new Date(reminder).toISOString() : null,note:el("edit-note").value})})).json();
    await update(item); message("进度与行动已保存，变化已加入时间线。");
  });});
  el("board-refresh").addEventListener("click",()=>act(async()=>{clean(); if(!profile)return; archive=await (await api(`/api/v1/candidate-profiles/${profile.id}`,{},profile,true)).json(); if(position)await loadPosition(position.id); else await loadList(); message("职位和材料已刷新。");}));
  el("position-edit").append(button("放弃未保存修改并重载",async()=>{dirty=false;await loadPosition(position.id);message("已重新载入所选职位。");}));
  el("position-generate").addEventListener("click",()=>act(async()=>{
    clean(); const data=await (await api(`/${position.id}/jobs`,{method:"POST",body:JSON.stringify({expected_revision:position.revision,expected_profile_revision:archive.revision})})).json();
    await update(data.position); await loadSources(); message("简历生成任务已创建。打开任务查看进度，完成并核对后再长期关联版本。");
  }));
  el("material-source").addEventListener("change",()=>act(async()=>{
    preview=null;versions=[];el("material-version").replaceChildren();el("material-consent").checked=false;
    const [kind,id]=el("material-source").value.split(":"); if(!id)return;
    if(kind==="run") { versions=await (await api(`/api/v1/tailor-runs/${id}/draft-versions`,{headers:{"X-Run-Token":profile.token}},profile,true)).json(); versions.forEach(version=>el("material-version").add(new Option(version.label,version.id))); }
    else { preview=await (await api(`/api/v1/candidate-profiles/${profile.id}/applications/${id}`,{},profile,true)).json(); el("material-version").add(new Option("已确认投递快照",preview.id)); }
    await showPreview(true);
  }));
  async function showPreview(preferActive=false) {
    el("material-consent").checked=false;
    const [kind,id]=el("material-source").value.split(":");
    if(kind==="run") {
      const job=await (await api(`/api/v1/tailor-runs/${id}/status`,{headers:{"X-Run-Token":profile.token}},profile,true)).json();
      if(preferActive && versions.some(version=>version.id===job.result?.active_version_id))el("material-version").value=job.result.active_version_id;
      const version=versions.find(version=>version.id===el("material-version").value);
      preview=version ? {draft:version.draft,jd_text:job.jd_text,target_company:job.target_company,target_role:job.target_job_title} : null;
    }
    el("material-preview").textContent=preview ? `${preview.target_company || ""} · ${preview.target_role || ""}\n来源 JD：\n${preview.jd_text}\n\n${preview.draft.markdown || JSON.stringify(preview.draft,null,2)}` : "请选择有效版本。";
  }
  el("material-version").addEventListener("change",()=>act(()=>showPreview()));
  el("material-link").addEventListener("click",()=>act(async()=>{
    clean();if(!preview || !el("material-consent").checked)throw new Error("请先核对所选版本，并同意长期关联。");
    const [kind,id]=el("material-source").value.split(":");
    const payload={expected_revision:position.revision,storage_consent:true,...(kind==="run" ? {run_id:id,version_id:el("material-version").value} : {application_id:id})};
    await update(await (await api(`/${position.id}/resumes`,{method:"POST",body:JSON.stringify(payload)})).json());el("material-consent").checked=false;message("简历已独立保存并设为当前投递版本；投递阶段仍需你手动确认。");
  }));
  el("practice-source").addEventListener("change",()=>{el("practice-consent").checked=false;});
  el("pack-source").addEventListener("change",()=>act(async()=>{
    const selected=materialPacks[Number(el("pack-source").value)];el("pack-consent").checked=false;
    if(el("pack-source").value==="" || !selected){el("pack-preview").textContent="";return;}
    const resume=position.resumes.find(item=>item.id===selected.resume_id), token=rememberedRuns().find(item=>item.id===resume.run_id)?.token || profile.token;
    const value=await (await api(`/api/v1/tailor-runs/${resume.run_id}/materials/${selected.pack.id}`,{headers:{"X-Run-Token":token}},profile,true)).json();
    selected.pack.revision=value.revision;
    el("pack-preview").textContent=`${value.company} · ${value.role}\n来源 JD：\n${value.jd_text}\n\n${value.documents.map(doc=>`${doc.title}\n${doc.content}\n${doc.issues.map(issue=>issue.reason).join("\n")}`).join("\n\n")}`;
  }));
  el("pack-link").addEventListener("click",()=>act(async()=>{
    clean(); const selected=materialPacks[Number(el("pack-source").value)];
    if(el("pack-source").value==="" || !selected || !el("pack-consent").checked)throw new Error("请选择材料包，核对内容并同意长期保存。");
    const resume=position.resumes.find(item=>item.id===selected.resume_id);
    await update(await (await api(`/${position.id}/materials`,{method:"POST",body:JSON.stringify({expected_revision:position.revision,resume_id:selected.resume_id,pack_id:selected.pack.id,expected_pack_revision:selected.pack.revision,run_token:rememberedRuns().find(item=>item.id===resume.run_id)?.token || "",storage_consent:true})})).json());
    message("求职材料包已独立长期保存。后续源材料编辑不会改变这份快照。");
  }));
  el("practice-link").addEventListener("click",()=>act(async()=>{
    clean();const item=practices[Number(el("practice-source").value)];
    if(el("practice-source").value==="" || !item || !el("practice-consent").checked)throw new Error("请选择练习并同意长期保存其中的回答与反馈。");
    await update(await (await api(`/${position.id}/interviews`,{method:"POST",body:JSON.stringify({expected_revision:position.revision,resume_id:item.resume_id,session_id:item.session.id,run_token:rememberedRuns().find(run=>run.id===position.resumes.find(resume=>resume.id===item.resume_id)?.run_id)?.token || "",storage_consent:true})})).json());message("面试报告已独立保存；后续练习不会修改这份快照。");
  }));
  el("position-delete").addEventListener("click",()=>act(async()=>{
    if(!confirm("删除此职位及工作台内的全部简历和面试快照？原任务和插件投递记录不会删除。"))return;
    await api(`/${position.id}`,{method:"DELETE"});position=null;dirty=false;el("board-detail").classList.add("hidden");await loadList();message("职位及关联快照已删除。");
  }));
  for(const id of ["board-stage","board-reminder"])el(id).addEventListener("change",()=>act(()=>loadList()));
  let searchTimer;el("board-search").addEventListener("input",()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>act(()=>loadList()),250);});
  setInterval(()=>{if(!document.hidden && !busy && profile)loadList().catch(error=>message(error.message));},60000);
  try {
    const saved=JSON.parse(localStorage.getItem("noworrycv-candidate-archives") || "[]");credentials=Array.isArray(saved) ? saved.filter(item=>item.id && item.token && item.label) : [];
    for(const item of credentials)el("board-profile").add(new Option(item.label,item.id));
    el("board-profile").value=new URLSearchParams(location.search).get("profile") || credentials[0]?.id || "";
    el("board-profile").dispatchEvent(new Event("change"));
  } catch(error) {message("无法读取本浏览器档案，请返回简历工作台重新连接。");controls();}
})();
