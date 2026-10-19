const preferenceLabels = { region: "目标国家 / 地区", job_family: "岗位族", hiring_track: "招聘类型", seniority: "目标资历", tone: "表达语气", page_count: "简历页数", template: "版式" };
let preferenceCatalog = null;
const preferencesReady = fetch("/api/v1/resume-preferences").then(async (response) => {
  if (!response.ok) throw new Error("无法读取偏好选项，请刷新重试。");
  preferenceCatalog = await response.json();
  const root = document.getElementById("preferences-fields");
  for (const [key, labelText] of Object.entries(preferenceLabels)) {
    const label = document.createElement("label"); label.className = "field compact";
    const span = document.createElement("span"); span.textContent = labelText;
    const select = document.createElement("select"); select.id = `pref-${key}`;
    for (const [value, label] of Object.entries(preferenceCatalog.options[key])) select.add(new Option(label, value));
    select.value = preferenceCatalog.defaults[key]; label.append(span, select); root.append(label);
    if (key === "template") label.hidden = true;
  }
});
preferencesReady.catch((error) => { document.getElementById("preferences-status").textContent = error.message; });

function readPreferences() {
  if (!preferenceCatalog) throw new Error("偏好选项尚未加载，请稍后重试。");
  return Object.fromEntries(Object.keys(preferenceCatalog.defaults).map((key) => [key,
    document.getElementById(key === "language" ? "output-language" : `pref-${key}`).value]));
}

async function setPreferences(preferences = {}) {
  await preferencesReady;
  for (const [key, value] of Object.entries({ ...preferenceCatalog.defaults, ...preferences })) {
    document.getElementById(key === "language" ? "output-language" : `pref-${key}`).value = value;
  }
  window.refreshTemplateSummaries?.();
}

function describePreferences(preferences = {}) {
  if (!preferenceCatalog) return "";
  return Object.entries({ ...preferenceCatalog.defaults, ...preferences }).map(([key, value]) => preferenceCatalog.options[key]?.[value] || value).join(" · ");
}

document.getElementById("save-preferences").addEventListener("click", async () => {
  if (!selectedArchive) return;
  const button = document.getElementById("save-preferences"); button.disabled = true;
  const status = document.getElementById("preferences-status");
  try {
    const archiveId = selectedArchive.id;
    const response = await fetch(`/api/v1/candidate-profiles/${archiveId}/preferences`, {
      method: "PATCH", headers: archiveRequestHeaders(),
      body: JSON.stringify({ preferences: readPreferences(), expected_preferences_revision: selectedArchive.preferences_revision || 1 }),
    });
    if (!response.ok) throw new Error(await getResponseError(response, "偏好保存失败。"));
    const archive = await response.json();
    if (selectedArchive?.id === archiveId) selectedArchive = archive;
    status.textContent = "常用偏好已保存。下次选择此档案时自动恢复；已生成的简历保持原版式。";
  } catch (error) { status.textContent = error.message; }
  finally { button.disabled = !selectedArchive || runIsBusy; }
});
