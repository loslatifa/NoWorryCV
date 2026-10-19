let templatePickerSelection = "";
let templatePickerApply = null;
const templateDialog = document.getElementById("template-dialog");

function resumeTemplateById(id) {
  return preferenceCatalog?.templates?.find(template => template.id === id);
}

function renderResumeTemplateSummary(rootId, id) {
  const root = document.getElementById(rootId);
  const template = resumeTemplateById(id);
  if (!root || !template) return;
  root.replaceChildren();
  const image = document.createElement("img");
  image.src = template.thumbnail_url;
  image.alt = `${template.name} 排版缩略图`;
  image.width = 54;
  image.height = 76;
  const copy = document.createElement("div");
  const name = document.createElement("strong");
  name.textContent = template.name;
  const description = document.createElement("p");
  description.textContent = template.adaptation === "flow" ? "来自你提供的模板 · 流式适配" : template.description;
  copy.append(name, description);
  root.append(image, copy);
}

function refreshTemplateSummaries() {
  renderResumeTemplateSummary("create-template-summary", document.getElementById("pref-template")?.value);
}

function syncTemplatePickerSelection() {
  const template = resumeTemplateById(templatePickerSelection);
  document.getElementById("template-apply").textContent = template ? `使用 ${template.name}` : "使用此模板";
  templateDialog.querySelectorAll("input[name=resume-template]").forEach(input => {
    input.checked = input.value === templatePickerSelection;
  });
}

async function openResumeTemplatePicker(value, onSelect) {
  await preferencesReady;
  templatePickerSelection = value;
  templatePickerApply = onSelect;
  const gallery = document.getElementById("template-gallery");
  gallery.replaceChildren();
  document.getElementById("template-example").hidden = true;
  gallery.hidden = false;
  const templates = preferenceCatalog.templates.filter(template => template.active || template.id === value);
  const supplied = templates.filter(template => template.adaptation === "flow").length;
  document.getElementById("template-catalog-status").textContent = `${supplied} 份提供的模板，另有 2 款基础版式。流式适配保留配色与文字层次，随内容自动分页。`;
  const issues = preferenceCatalog.template_issues || [];
  const notice = document.getElementById("template-import-issues");
  notice.hidden = !issues.length;
  notice.textContent = issues.map(issue => `${issue.filename}：${issue.reason}`).join("；");
  // User supplied templates come first; the previous built-in choices remain available.
  templates.sort((a, b) => Number(a.adaptation === "builtin") - Number(b.adaptation === "builtin"));
  templates.forEach(template => {
    const card = document.createElement("article");
    card.className = "template-card";
    const choice = document.createElement("label");
    choice.className = "template-card-choice";
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "resume-template";
    radio.value = template.id;
    radio.setAttribute("aria-label", template.name);
    radio.addEventListener("change", () => {
      templatePickerSelection = radio.value;
      syncTemplatePickerSelection();
    });
    const image = document.createElement("img");
    image.src = template.thumbnail_url;
    image.alt = `${template.name} 版式预览`;
    image.loading = "lazy";
    const name = document.createElement("strong");
    name.textContent = template.name;
    const badge = document.createElement("span");
    badge.className = "template-badge";
    badge.textContent = template.suggested_pages === 2 ? "双页参考版 · 自动分页" : template.adaptation === "flow" ? "流式适配" : "基础版式";
    choice.append(radio, image, name, badge);
    const preview = document.createElement("button");
    preview.type = "button";
    preview.className = "template-example-button";
    preview.textContent = "放大查看示例";
    preview.addEventListener("click", () => {
      templatePickerSelection = template.id;
      syncTemplatePickerSelection();
      gallery.hidden = true;
      document.getElementById("template-example").hidden = false;
      document.getElementById("template-example-name").textContent = template.name;
      document.getElementById("template-example-frame").src = template.preview_url;
      document.getElementById("template-example-link").href = template.preview_url;
      document.getElementById("template-example-back").focus();
    });
    card.append(choice, preview);
    gallery.appendChild(card);
  });
  syncTemplatePickerSelection();
  templateDialog.showModal();
  templateDialog.querySelector("input:checked")?.focus({preventScroll:true});
}

document.getElementById("template-apply").addEventListener("click", () => {
  if (templatePickerSelection && templatePickerApply) templatePickerApply(templatePickerSelection);
  templateDialog.close();
});
document.getElementById("template-close").addEventListener("click", () => templateDialog.close());
templateDialog.addEventListener("close", () => {
  document.getElementById("template-example-frame").removeAttribute("src");
  templatePickerApply = null;
});
document.getElementById("template-example-back").addEventListener("click", () => {
  document.getElementById("template-example").hidden = true;
  document.getElementById("template-gallery").hidden = false;
  document.getElementById("template-example-frame").removeAttribute("src");
  templateDialog.querySelector("input:checked")?.focus({preventScroll:true});
});

preferencesReady.then(() => {
  const select = document.getElementById("pref-template");
  refreshTemplateSummaries();
  select.addEventListener("change", refreshTemplateSummaries);
  document.getElementById("choose-template-button").disabled = false;
  document.getElementById("choose-template-button").addEventListener("click", () => {
    openResumeTemplatePicker(select.value, value => {
      select.value = value;
      refreshTemplateSummaries();
    });
  });
}).catch(() => {
  document.getElementById("create-template-summary").textContent = "模板暂时无法加载，请刷新重试。";
});
