(function installWorkspace() {
  const views = [...document.querySelectorAll("[data-workspace-view]")];
  if (!views.length) return;
  const names = { create: "简历定制", result: "简历结果", history: "任务历史", quality: "反馈与质量" };
  const breadcrumb = document.getElementById("workspace-breadcrumb");
  const initialView = location.hash.slice(1);
  let keepChosenView = Object.hasOwn(names, initialView) && initialView !== "result";

  function showView(key, { focus = false, remember = false } = {}) {
    if (!Object.hasOwn(names, key)) key = "create";
    views.forEach(view => { view.hidden = view.dataset.workspaceView !== key; });
    document.querySelectorAll(".workspace-sidebar [data-workspace-target]").forEach(button => {
      const active = button.dataset.workspaceTarget === key;
      button.classList.toggle("active", active);
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    breadcrumb.textContent = names[key];
    if (remember && location.hash !== `#${key}`) {
      const url = new URL(location.href);
      url.hash = key;
      history.pushState(null, "", url);
    }
    if (focus) {
      document.querySelector(`[data-workspace-view="${key}"] h1`)?.focus({ preventScroll: true });
      window.scrollTo({ top: 0, behavior: "instant" });
    }
  }

  const tabs = [...document.querySelectorAll("[data-result-target]")];
  function showResultTab(key, focus = false) {
    if (!tabs.some(tab => tab.dataset.resultTarget === key)) return;
    tabs.forEach(tab => {
      const selected = tab.dataset.resultTarget === key;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      if (selected && focus) tab.focus();
    });
    document.querySelectorAll(".result-tab-panel").forEach(panel => {
      panel.hidden = panel.id !== `result-section-${key}`;
    });
  }

  document.addEventListener("click", event => {
    const target = event.target.closest("[data-workspace-target]");
    if (target) {
      keepChosenView = !(target.dataset.workspaceTarget === "create" && visible(waiting));
      showView(target.dataset.workspaceTarget, { focus: true, remember: true });
    }
    const tab = event.target.closest("[data-result-target]");
    if (tab) showResultTab(tab.dataset.resultTarget);
  });
  document.querySelector(".result-tabs")?.addEventListener("keydown", event => {
    const index = tabs.indexOf(document.activeElement);
    if (index < 0 || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1
      : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    showResultTab(tabs[next].dataset.resultTarget, true);
  });
  function restoreView() {
    keepChosenView = true;
    showView(location.hash.slice(1), { focus: true });
  }
  window.addEventListener("hashchange", restoreView);
  window.addEventListener("popstate", restoreView);

  const result = document.getElementById("result-root");
  const confirmation = document.getElementById("confirmation-panel");
  const waiting = document.getElementById("waiting-panel");
  let wasReady = false;
  const visible = node => !node.classList.contains("hidden");
  let wasReviewing = visible(confirmation);
  let wasProcessing = visible(waiting);
  function syncWorkflow() {
    const ready = visible(result);
    const reviewing = visible(confirmation);
    const processing = visible(waiting);
    document.getElementById("result-pending").hidden = !processing || ready;
    document.body.classList.toggle("workspace-processing", processing);
    const step = ready || processing ? 3 : reviewing ? 2 : 1;
    document.querySelectorAll("[data-workflow-step]").forEach(item => {
      const current = Number(item.dataset.workflowStep);
      item.classList.toggle("active", current === step);
      item.classList.toggle("done", current < step);
      if (current === step) item.setAttribute("aria-current", "step");
      else item.removeAttribute("aria-current");
    });
    const startingActivity = reviewing && !wasReviewing || processing && !wasProcessing;
    if (startingActivity) keepChosenView = false;
    if (ready && !wasReady && !keepChosenView) {
      showResultTab("editor");
      showView("result", { focus: true, remember: true });
    } else if (!ready && startingActivity) {
      showView("create", { remember: true });
    }
    wasReady = ready;
    wasReviewing = reviewing;
    wasProcessing = processing;
  }
  const observer = new MutationObserver(syncWorkflow);
  [result, confirmation, waiting].forEach(node => observer.observe(node, { attributes: true, attributeFilter: ["class"] }));
  showView(location.hash.slice(1));
  syncWorkflow();

  const file = document.getElementById("resume-file");
  const fileField = document.getElementById("resume-file-field");
  file.addEventListener("change", () => { fileField.classList.toggle("has-file", file.files.length > 0); });
  document.getElementById("tailor-form").addEventListener("reset", () => fileField.classList.remove("has-file"));
})();
