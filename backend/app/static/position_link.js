(() => {
  const el=id=>document.getElementById(id);
  let context=null, positions=[], epoch=0;
  async function load() {
    const sequence=++epoch, id=el("position-link-profile").value;
    const credential=archiveCredentials.find(item=>item.id===id);
    el("position-link-consent").checked=false;el("position-link-position").replaceChildren();el("position-link-save").disabled=true;
    if(!credential){el("position-link-status").textContent="先保存基础档案，再到工作台新增职位。";return;}
    try {
      const response=await fetch(`/api/v1/candidate-profiles/${id}/positions`,{headers:{"X-Profile-Token":credential.token}});
      if(!response.ok)throw new Error(await getResponseError(response,"职位列表无法载入。"));
      const data=await response.json();if(sequence!==epoch)return;positions=data.items;
      el("position-link-position").add(new Option("请选择目标职位", ""));
      for(const item of positions)el("position-link-position").add(new Option(`${item.company} · ${item.role}`,item.id));
      el("position-link-status").textContent=positions.length ? "请选择目标职位并核对当前已保存版本。" : "此档案尚无职位，请打开工作台新增职位。";
    } catch(error){if(sequence===epoch)el("position-link-status").textContent=error.message;}
  }
  window.initializePositionLink=(runId,versionId)=>{
    context={runId,versionId,token:currentRunToken};el("position-link-consent").checked=false;el("position-link-jd").textContent="";
    const previous=el("position-link-profile").value;el("position-link-profile").replaceChildren();
    for(const item of archiveCredentials)el("position-link-profile").add(new Option(item.label,item.id));
    el("position-link-profile").value=previous || selectedArchive?.id || archiveCredentials[0]?.id || "";load();
  };
  el("position-link-profile").addEventListener("change",load);
  el("position-link-position").addEventListener("change",async()=>{
    const sequence=++epoch, credential=archiveCredentials.find(item=>item.id===el("position-link-profile").value), id=el("position-link-position").value;
    el("position-link-consent").checked=false;el("position-link-save").disabled=true;el("position-link-jd").textContent="";
    if(!credential || !id)return;
    try {
      const response=await fetch(`/api/v1/candidate-profiles/${credential.id}/positions/${id}`,{headers:{"X-Profile-Token":credential.token}});
      if(!response.ok)throw new Error(await getResponseError(response,"职位无法载入。"));
      const record=await response.json();if(sequence!==epoch)return;
      positions=positions.map(item=>item.id===id ? record : item);el("position-link-jd").textContent=`目标职位 JD：${record.jd_text}`;el("position-link-save").disabled=false;
    } catch(error){if(sequence===epoch)el("position-link-status").textContent=error.message;}
  });
  el("position-link-save").addEventListener("click",async()=>{
    const sequence=epoch, snapshot=context, credential=archiveCredentials.find(item=>item.id===el("position-link-profile").value);
    const position=positions.find(item=>item.id===el("position-link-position").value);
    if(!snapshot || !credential || !position)return;
    if(draftIsDirty || draftMutationInProgress){el("position-link-status").textContent="请先保存当前简历编辑，再关联版本。";return;}
    if(!el("position-link-consent").checked){el("position-link-status").textContent="请核对当前版本、目标职位并同意长期关联。";return;}
    el("position-link-save").disabled=true;
    try {
      const response=await fetch(`/api/v1/candidate-profiles/${credential.id}/positions/${position.id}/resumes`,{method:"POST",headers:{"Content-Type":"application/json","X-Profile-Token":credential.token},body:JSON.stringify({run_id:snapshot.runId,version_id:snapshot.versionId,run_token:snapshot.token,expected_revision:position.revision,storage_consent:true})});
      if(!response.ok)throw new Error(await getResponseError(response,"关联失败，请重新选择职位载入最新记录。"));
      const record=await response.json();if(sequence!==epoch)return;
      positions=positions.map(item=>item.id===record.id ? record : item);el("position-link-consent").checked=false;el("position-link-status").textContent="当前版本已长期关联到职位；投递阶段没有自动改变。";
    } catch(error){if(sequence===epoch)el("position-link-status").textContent=error.message;}
    finally{if(sequence===epoch)el("position-link-save").disabled=false;}
  });
  if(currentRunId && activeVersionId && currentDraft)window.initializePositionLink(currentRunId,activeVersionId);
})();
