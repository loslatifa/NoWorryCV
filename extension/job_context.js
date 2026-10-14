(function installJobContext() {
  if (window.__noworrycvJobContextInstalled) return;
  window.__noworrycvJobContextInstalled = true;

  function plain(value) {
    const parsed = new DOMParser().parseFromString(String(value || ""), "text/html");
    return (parsed.body.textContent || "").trim().slice(0, 30000);
  }

  function findJob(value) {
    if (!value || typeof value !== "object") return null;
    if ([value["@type"]].flat().includes("JobPosting")) return value;
    for (const nested of Object.values(value)) {
      if (nested && typeof nested === "object") {
        const found = findJob(nested);
        if (found) return found;
      }
    }
    return null;
  }

  function extractJob() {
    let job = null;
    for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
      if (script.textContent.length > 500000) continue;
      try { job = findJob(JSON.parse(script.textContent)); } catch { /* Other schema markup. */ }
      if (job) break;
    }
    const candidates = Array.from(document.querySelectorAll(
      '[data-job-description], [itemprop="description"], .job-description, .job-detail, #job-description, [class*="jobDescription"], [class*="job-description"], main, article'
    )).map(el => el.innerText || "").filter(text => /岗位职责|任职要求|职位描述|招聘要求|responsibilit|qualification|requirements/i.test(text));
    const text = job ? [plain(job.description), plain(job.responsibilities), plain(job.qualifications), plain(job.skills)].filter(Boolean).join("\n") : (candidates.sort((a, b) => a.length - b.length)[0] || "");
    return {
      page_url: location.href, job_url: location.href,
      target_role: plain(job?.title || document.querySelector('h1, [itemprop="title"]')?.textContent).slice(0, 120),
      target_company: plain(job?.hiringOrganization?.name || document.querySelector('[itemprop="hiringOrganization"]')?.textContent).slice(0, 120),
      jd_text: text.trim().slice(0, 30000),
      source: job ? "JobPosting 结构化数据" : text ? "岗位正文" : "未找到岗位要求，请粘贴 JD 或先在岗位详情页识别",
      upload_inputs: Array.from(document.querySelectorAll('input[type="file"]')).map((el, index) => {
        el.setAttribute("data-noworrycv-upload", String(index));
        return { selector: `[data-noworrycv-upload="${index}"]`,
          label: document.querySelector(`label[for="${CSS.escape(el.id)}"]`)?.textContent?.trim() || el.getAttribute("aria-label") || el.name || "未标注的附件",
          accept: el.accept, disabled: el.disabled, files: Array.from(el.files || []).map(file => file.name) };
      })
    };
  }

  function attach(message) {
    if (location.href !== message.page_url) throw new Error("页面已跳转，请回到原投递页面。");
    const element = document.querySelector(message.selector);
    if (!element || element.type !== "file" || element.disabled) throw new Error("附件字段已变化，请重新检测。");
    const binary = atob(message.data);
    const bytes = Uint8Array.from(binary, char => char.charCodeAt(0));
    const file = new File([bytes], message.filename, { type: message.media_type });
    const accept = element.accept.toLowerCase();
    const extension = `.${message.filename.split(".").pop().toLowerCase()}`;
    if (accept && !accept.split(",").some(item => [extension, file.type, "application/*", "*/*"].includes(item.trim()))) {
      throw new Error("此附件字段不接受当前简历格式，请选择其他字段或下载后上传。");
    }
    const transfer = new DataTransfer();
    transfer.items.add(file);
    element.files = transfer.files;
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
    if (element.files?.[0]?.name !== file.name) throw new Error("页面未接受文件，请下载简历后手动上传。");
    return { filename: file.name };
  }

  chrome.runtime.onMessage.addListener((message, sender, respond) => {
    try {
      if (message.type === "EXTRACT_JOB_CONTEXT") respond({ ok: true, job: extractJob() });
      else if (message.type === "ATTACH_CONFIRMED_RESUME") respond({ ok: true, ...attach(message) });
      else return false;
    } catch (error) { respond({ ok: false, error: error.message }); }
    return false;
  });
})();
