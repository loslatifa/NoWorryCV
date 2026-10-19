(function installJobAutoAgentContentScript() {
  if (window.__jobAutoAgentContentScriptInstalled) {
    return;
  }
  window.__jobAutoAgentContentScriptInstalled = true;
  window.__jobAutoAgentLastFillSession = window.__jobAutoAgentLastFillSession || null;

  const HIGHLIGHT_ATTR = "data-job-auto-agent-highlight";
  const FIELD_SELECTOR = [
    "input:not([type='hidden']):not([type='submit']):not([type='button']):not([type='reset']):not([type='image']):not([type='file'])",
    "select",
    "textarea"
  ].join(", ");
  const ACTION_SELECTOR = [
    "button",
    "a[href]",
    "[role='button']",
    "[data-add-section]",
    "[class*='add']",
    "[class*='plus']",
    "[class*='button']"
  ].join(", ");

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    try {
      if (message?.type === "PING") {
        sendResponse({ ok: true, installed: true });
        return false;
      }
      if (message?.type === "EXTRACT_FIELDS") {
        sendResponse({ ok: true, fields: extractFormFields() });
        return false;
      }
      if (message?.type === "FILL_FIELDS") {
        if (message.page_url && message.page_url !== location.href) throw new Error("投递页面已变化，请重新检测。");
        fillMappedFields(message.mappings || [])
          .then(payload => sendResponse({ ok: true, ...payload }))
          .catch(error => sendResponse({ ok: false, error: error.message }));
        return true;
      }
      if (message?.type === "CLEAR_HIGHLIGHTS") {
        sendResponse({ ok: true, cleared: clearHighlights() });
        return false;
      }
      if (message?.type === "UNDO_LAST_FILL") {
        sendResponse({ ok: true, ...undoLastFill() });
        return false;
      }
      if (message?.type === "CLEAR_FILL_SESSION") {
        sendResponse({ ok: true, ...clearFillSession() });
        return false;
      }
      if (message?.type === "EXTRACT_ACTION_BUTTONS") {
        sendResponse({ ok: true, buttons: extractActionButtons() });
        return false;
      }
      if (message?.type === "CLICK_ACTION") {
        clickAction(message.selector)
          .then((payload) => sendResponse({ ok: true, ...payload }))
          .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
        return true;
      }
      if (message?.type === "WAIT_FOR_FORM_MUTATION") {
        waitForFormMutation(message.timeoutMs || 1200)
          .then((payload) => sendResponse({ ok: true, ...payload }))
          .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
        return true;
      }
    } catch (error) {
      sendResponse({ ok: false, error: error.message || String(error) });
      return false;
    }
    return false;
  });

  function extractFormFields() {
    return Array.from(document.querySelectorAll(FIELD_SELECTOR))
      .filter(isVisibleFormField)
      .map((element, index) => {
        const selector = generateUniqueSelector(element);
        return {
          index,
          selector,
          tag: element.tagName.toLowerCase(),
          type: getFieldType(element),
          label: findLabel(element),
          placeholder: element.getAttribute("placeholder") || "",
          name: element.getAttribute("name") || "",
          id: element.id || "",
          required: Boolean(element.required || element.getAttribute("aria-required") === "true"),
          value: getCurrentValue(element),
          options: extractOptions(element),
          multiple: Boolean(element.multiple),
          date_part: element.getAttribute("data-date-part") || "",
          min: element.getAttribute("min") || "",
          max: element.getAttribute("max") || "",
          step: element.getAttribute("step") || "",
        section: findParentSection(element),
        semantic_hints: collectSemanticHints(element, selector).join(" "),
        dom_context: findDomTextContext(element),
        repeatable_type: element.getAttribute("data-repeatable-type") || findRepeatableType(element),
        repeatable_index: element.getAttribute("data-repeatable-index") || findRepeatableIndex(element),
        field_role: element.getAttribute("data-field-role") || "",
        disabled: Boolean(element.disabled),
        read_only: Boolean(element.readOnly)
      };
      });
  }

  async function fillMappedFields(mappings) {
    clearHighlights();
    const session = {
      session_id: `fill-${Date.now()}`,
      changed_fields: []
    };

    const results = mappings.map((mapping) => {
      const selector = mapping.selector || mapping.field_selector;
      const element = selector ? document.querySelector(selector) : null;
      const baseResult = {
        selector,
        field_label: mapping.field_label || "",
        matched_resume_path: mapping.matched_resume_path || null,
        fill_value: mapping.fill_value || "",
        confidence: Number(mapping.confidence) || 0
      };
      if (!element) {
        return { ...baseResult, status: "failed", reason: "Element not found." };
      }

      highlightField(element, mapping.confidence);

      if (mapping.enabled === false) {
        return { ...baseResult, status: "skipped_disabled_by_user", reason: "Disabled in fill preview." };
      }
      if ((Number(mapping.confidence) || 0) < 0.6 && mapping.enabled !== true) {
        return { ...baseResult, status: "skipped_low_confidence", reason: "Confidence below 0.6." };
      }
      if (!mapping.fill_value || !mapping.matched_resume_path) {
        return { ...baseResult, status: "skipped_empty", reason: "No mapped resume value." };
      }
      if (element.disabled || element.readOnly) {
        return { ...baseResult, status: "skipped_disabled", reason: "Field is disabled or read-only." };
      }

      const beforeValue = getRawValue(element);
      const filled = fillField(element, String(mapping.fill_value));
      if (getRawValue(element) !== beforeValue) {
        session.changed_fields.push({
          selector,
          field_type: getFieldType(element),
          before_value: beforeValue,
          after_value: getRawValue(element)
        });
      }
      return {
        ...baseResult,
        selector,
        status: filled ? "filled" : "failed",
        reason: filled ? "" : element.validationMessage || "控件未接受该值，需人工填写。",
        original_value: beforeValue,
        final_value: getRawValue(element)
      };
    });

    window.__jobAutoAgentLastFillSession = session;
    // Controlled components can restore their state after the dispatched events.
    await new Promise(resolve => setTimeout(resolve, 150));
    for (const result of results) {
      if (result.status !== "filled") continue;
      const element = document.querySelector(result.selector);
      if (!element || getRawValue(element) !== result.final_value) {
        result.status = "failed";
        result.reason = "页面重新渲染后未保留填写值，请人工处理此控件。";
      }
    }
    return {
      session_id: session.session_id,
      filled_count: results.filter((result) => result.status === "filled").length,
      skipped_count: results.filter((result) => result.status.startsWith("skipped")).length,
      failed_count: results.filter((result) => result.status === "failed").length,
      low_confidence_count: results.filter((result) => result.status === "skipped_low_confidence").length,
      results
    };
  }

  function undoLastFill() {
    const session = window.__jobAutoAgentLastFillSession;
    if (!session || !Array.isArray(session.changed_fields) || !session.changed_fields.length) {
      return { restored_count: 0, results: [], reason: "No fill session to undo." };
    }

    const results = [];
    session.changed_fields.slice().reverse().forEach((field) => {
      const element = document.querySelector(field.selector);
      if (!element) {
        results.push({ selector: field.selector, status: "failed", reason: "Element not found." });
        return;
      }
      const restored = restoreField(element, field.before_value);
      results.push({
        selector: field.selector,
        status: restored ? "restored" : "failed",
        reason: restored ? "" : "Unsupported field type."
      });
    });

    clearFillSession();
    return {
      session_id: session.session_id,
      restored_count: results.filter((result) => result.status === "restored").length,
      results
    };
  }

  function clearFillSession() {
    const cleared = clearHighlights();
    window.__jobAutoAgentLastFillSession = null;
    return { cleared_highlights: cleared, cleared_session: true };
  }

  function extractActionButtons() {
    return Array.from(document.querySelectorAll(ACTION_SELECTOR))
      .filter(isVisibleAction)
      .map((element) => {
        const selector = generateUniqueSelector(element);
        const text = cleanupLabelText(getReadableText(element) || element.textContent || "");
        const context = findActionContext(element);
        return {
          selector,
          text,
          aria_label: cleanupLabelText(element.getAttribute("aria-label") || ""),
          title: cleanupLabelText(element.getAttribute("title") || ""),
          section: context.section,
          nearby_context: context.nearby_context,
          semantic_hints: collectSemanticHints(element, selector).join(" "),
          disabled: Boolean(element.disabled || element.getAttribute("aria-disabled") === "true")
        };
      })
      .filter((button) => isPotentialAddButton(button) && !isDangerousAction(button));
  }

  async function clickAction(selector) {
    if (!selector) {
      throw new Error("Missing action selector.");
    }
    const element = document.querySelector(selector);
    if (!element) {
      throw new Error(`Action element not found: ${selector}`);
    }
    if (!isVisibleAction(element)) {
      throw new Error(`Action element is not visible or enabled: ${selector}`);
    }

    const buttonPayload = {
      text: cleanupLabelText(getReadableText(element) || element.textContent || ""),
      aria_label: cleanupLabelText(element.getAttribute("aria-label") || ""),
      title: cleanupLabelText(element.getAttribute("title") || ""),
      section: findActionContext(element).section,
      nearby_context: findActionContext(element).nearby_context,
      semantic_hints: collectSemanticHints(element, selector).join(" ")
    };
    if (isDangerousAction(buttonPayload) || !isPotentialAddButton(buttonPayload)) {
      throw new Error("Refusing to click an unsafe or non-add action.");
    }

    const waitPromise = waitForFormMutation(1500);
    element.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, view: window }));
    element.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, view: window }));
    element.click();
    const mutation = await waitPromise;
    return { clicked: true, mutation };
  }

  function waitForFormMutation(timeoutMs = 1200) {
    return new Promise((resolve) => {
      const beforeCount = document.querySelectorAll(FIELD_SELECTOR).length;
      let settled = false;
      const observer = new MutationObserver(() => {
        const afterCount = document.querySelectorAll(FIELD_SELECTOR).length;
        if (afterCount !== beforeCount && !settled) {
          settled = true;
          observer.disconnect();
          resolve({ changed: true, before_count: beforeCount, after_count: afterCount });
        }
      });

      observer.observe(document.body, { childList: true, subtree: true });
      window.setTimeout(() => {
        if (!settled) {
          observer.disconnect();
          resolve({
            changed: document.querySelectorAll(FIELD_SELECTOR).length !== beforeCount,
            before_count: beforeCount,
            after_count: document.querySelectorAll(FIELD_SELECTOR).length
          });
        }
      }, timeoutMs);
    });
  }

  function fillField(element, value) {
    const tag = element.tagName.toLowerCase();
    if (tag === "select") {
      return fillSelect(element, value);
    }
    if (tag === "textarea") {
      setNativeValue(element, value, window.HTMLTextAreaElement.prototype);
      dispatchFormEvents(element);
      return element.value === value;
    }
    if (tag === "input") {
      if (["checkbox", "radio", "password"].includes(element.type)) return false;
      const prepared = NoWorryCVFormControls.prepareValue(controlMetadata(element), value);
      if (prepared.reason) return false;
      const before = element.value;
      setNativeValue(element, prepared.value, window.HTMLInputElement.prototype);
      if (element.value !== prepared.value || !element.validity.valid) {
        // Browser sanitization or min/max/step rejection must not erase existing data.
        setNativeValue(element, before, window.HTMLInputElement.prototype);
        return false;
      }
      dispatchFormEvents(element);
      return element.value === prepared.value && element.validity.valid;
    }
    return false;
  }

  function restoreField(element, value) {
    const tag = element.tagName.toLowerCase();
    if (tag === "select") {
      setNativeValue(element, value, window.HTMLSelectElement.prototype);
      dispatchFormEvents(element);
      return true;
    }
    if (tag === "textarea") {
      setNativeValue(element, value, window.HTMLTextAreaElement.prototype);
      dispatchFormEvents(element);
      return true;
    }
    if (tag === "input") {
      setNativeValue(element, value, window.HTMLInputElement.prototype);
      dispatchFormEvents(element);
      return true;
    }
    return false;
  }

  function fillSelect(select, value) {
    const option = NoWorryCVFormControls.selectOption(controlMetadata(select), value);
    if (!option) return false;
    const before = select.value;
    setNativeValue(select, String(option.value), window.HTMLSelectElement.prototype);
    if (select.value !== String(option.value) || !select.validity.valid) {
      setNativeValue(select, before, window.HTMLSelectElement.prototype);
      return false;
    }
    dispatchFormEvents(select);
    return select.value === String(option.value) && select.validity.valid;
  }

  function controlMetadata(element) {
    return {
      type: getFieldType(element), tag: element.tagName.toLowerCase(),
      label: findLabel(element), name: element.name || "", id: element.id || "",
      field_role: element.getAttribute("data-field-role") || "",
      date_part: element.getAttribute("data-date-part") || "",
      min: element.getAttribute("min") || "", max: element.getAttribute("max") || "",
      multiple: Boolean(element.multiple), options: extractOptions(element)
    };
  }

  function setNativeValue(element, value, prototype) {
    const valueSetter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
    if (valueSetter) {
      valueSetter.call(element, value);
    } else {
      element.value = value;
    }
  }

  function dispatchFormEvents(element) {
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
    element.dispatchEvent(new Event("blur", { bubbles: true }));
  }

  function highlightField(element, confidence) {
    const score = Number(confidence) || 0;
    const color = score >= 0.8 ? "#22c55e" : score >= 0.6 ? "#f59e0b" : "#ef4444";
    element.setAttribute(HIGHLIGHT_ATTR, "true");
    element.dataset.jobAutoAgentOriginalOutline = element.style.outline || "";
    element.dataset.jobAutoAgentOriginalBoxShadow = element.style.boxShadow || "";
    element.style.outline = `3px solid ${color}`;
    element.style.boxShadow = `0 0 0 4px ${hexToRgba(color, 0.16)}`;
  }

  function clearHighlights() {
    const highlighted = Array.from(document.querySelectorAll(`[${HIGHLIGHT_ATTR}='true']`));
    highlighted.forEach((element) => {
      element.style.outline = element.dataset.jobAutoAgentOriginalOutline || "";
      element.style.boxShadow = element.dataset.jobAutoAgentOriginalBoxShadow || "";
      delete element.dataset.jobAutoAgentOriginalOutline;
      delete element.dataset.jobAutoAgentOriginalBoxShadow;
      element.removeAttribute(HIGHLIGHT_ATTR);
    });
    return highlighted.length;
  }

  function generateUniqueSelector(element) {
    if (element.id) {
      const idSelector = `#${cssEscape(element.id)}`;
      if (isUnique(idSelector)) {
        return idSelector;
      }
    }

    if (element.name) {
      const nameSelector = `${element.tagName.toLowerCase()}[name="${escapeAttribute(element.name)}"]`;
      if (isUnique(nameSelector)) {
        return nameSelector;
      }
    }

    const parts = [];
    let current = element;
    while (current && current.nodeType === Node.ELEMENT_NODE && current !== document.documentElement) {
      let part = current.tagName.toLowerCase();
      if (current.id) {
        part += `#${cssEscape(current.id)}`;
        parts.unshift(part);
        break;
      }

      const sameTagSiblings = Array.from(current.parentElement?.children || [])
        .filter((sibling) => sibling.tagName === current.tagName);
      if (sameTagSiblings.length > 1) {
        part += `:nth-of-type(${sameTagSiblings.indexOf(current) + 1})`;
      }

      parts.unshift(part);
      const selector = parts.join(" > ");
      if (isUnique(selector)) {
        return selector;
      }
      current = current.parentElement;
    }

    return parts.join(" > ");
  }

  function isUnique(selector) {
    try {
      return document.querySelectorAll(selector).length === 1;
    } catch (error) {
      return false;
    }
  }

  function findLabel(element) {
    const explicitLabel = findExplicitLabel(element);
    if (explicitLabel) {
      return explicitLabel;
    }

    const parentLabel = element.closest("label");
    if (parentLabel) {
      const text = cleanupLabelText(parentLabel.textContent || "");
      if (text) {
        return text;
      }
    }

    const ariaLabel = element.getAttribute("aria-label");
    if (ariaLabel) {
      return cleanupLabelText(ariaLabel);
    }

    const ariaLabelledBy = findAriaLabelledBy(element);
    if (ariaLabelledBy) {
      return ariaLabelledBy;
    }

    const frameworkLabel = findFrameworkLabel(element);
    if (frameworkLabel) {
      return frameworkLabel;
    }

    const nearby = findNearbyText(element);
    if (nearby) {
      return nearby;
    }

    return cleanupLabelText(element.getAttribute("placeholder") || inferLabelFromSemanticHints(element));
  }

  function findExplicitLabel(element) {
    if (!element.id) {
      return "";
    }
    const label = document.querySelector(`label[for="${cssEscape(element.id)}"]`);
    return label ? cleanupLabelText(label.textContent || "") : "";
  }

  function findAriaLabelledBy(element) {
    const labelledBy = element.getAttribute("aria-labelledby");
    if (!labelledBy) {
      return "";
    }
    return labelledBy
      .split(/\s+/)
      .map((id) => document.getElementById(id)?.textContent || "")
      .map(cleanupLabelText)
      .filter(Boolean)
      .join(" ");
  }

  function findNearbyText(element) {
    const previous = collectPreviousSiblingText(element);
    if (previous) {
      return previous;
    }

    const container = findFieldContainer(element);
    if (!container) {
      return "";
    }

    const labelLike = container.querySelector("label, .label, [class*='label'], [class*='title']");
    if (labelLike && !isFormControl(labelLike)) {
      const text = cleanupLabelText(getReadableText(labelLike));
      if (isLikelyLabelText(text)) {
        return text;
      }
    }

    return "";
  }

  function findFrameworkLabel(element) {
    const containers = collectAncestorElements(element, 8);
    const labelSelectors = [
      ".semi-form-field-label",
      ".semi-form-field-label-text",
      ".ant-form-item-label",
      ".arco-form-label-item",
      ".arco-form-item-label",
      ".el-form-item__label",
      ".formily-element-form-item-label",
      ".formily-item-label",
      "[class*='form-item-label']",
      "[class*='field-label']",
      "[class*='label']",
      "label"
    ];

    for (const container of containers) {
      for (const selector of labelSelectors) {
        const candidates = Array.from(container.querySelectorAll(selector));
        for (const candidate of candidates) {
          if (candidate.contains(element)) {
            continue;
          }
          const text = cleanupLabelText(getReadableText(candidate));
          if (isLikelyLabelText(text)) {
            return text;
          }
        }
      }
    }

    for (const container of containers) {
      const textBeforeField = getTextBeforeElement(container, element);
      if (isLikelyLabelText(textBeforeField)) {
        return textBeforeField;
      }
    }

    return "";
  }

  function collectPreviousSiblingText(element) {
    const texts = [];
    let sibling = element.previousElementSibling;
    let hops = 0;
    while (sibling && hops < 3) {
      if (!isFormControl(sibling)) {
        const text = cleanupLabelText(sibling.textContent || "");
        if (text) {
          texts.unshift(text);
        }
      }
      sibling = sibling.previousElementSibling;
      hops += 1;
    }
    return texts.join(" ").trim();
  }

  function findParentSection(element) {
    const section = element.closest("fieldset, section, form, [role='group'], .section, .form-section, .ant-card, .el-card");
    if (!section) {
      return "";
    }
    // A form can contain multiple unrelated fieldsets; their legends are not its label.
    if (section.tagName === "FORM") return cleanupLabelText(section.getAttribute("aria-label") || "");

    const legend = section.querySelector("legend");
    if (legend) {
      return cleanupLabelText(legend.textContent || "");
    }

    const heading = section.querySelector("h1, h2, h3, h4, [class*='title']");
    if (heading) {
      return cleanupLabelText(heading.textContent || "");
    }

    return cleanupLabelText(section.getAttribute("aria-label") || "");
  }

  function findDomTextContext(element) {
    const container = findFieldContainer(element);
    if (!container) {
      return collectPreviousSiblingText(element);
    }

    const text = cleanupLabelText(getReadableText(container));
    if (!text) {
      return "";
    }
    return text.length > 180 ? text.slice(0, 180) : text;
  }

  function findFieldContainer(element) {
    return element.closest([
      "[id^='formily-item']",
      "[id*='formily-item']",
      "[class*='formily']",
      ".semi-form-field",
      ".semi-form-field-main",
      ".ant-form-item",
      ".arco-form-item",
      ".el-form-item",
      ".field",
      ".form-field",
      ".form-item",
      ".form-group",
      ".input-group",
      "[class*='field']",
      "[class*='form']"
    ].join(", "));
  }

  function collectSemanticHints(element, selector) {
    const hints = new Set();
    collectElementHints(element).forEach((hint) => hints.add(hint));
    hints.add(selector || "");

    let current = element.parentElement;
    let depth = 0;
    while (current && current !== document.body && depth < 8) {
      collectElementHints(current).forEach((hint) => hints.add(hint));
      current = current.parentElement;
      depth += 1;
    }

    return Array.from(hints)
      .map(cleanupSemanticHint)
      .filter((hint) => hint.length >= 2)
      .slice(0, 40);
  }

  function collectElementHints(element) {
    const hints = [
      element.id,
      element.getAttribute("name"),
      element.getAttribute("type"),
      element.getAttribute("role"),
      element.getAttribute("placeholder"),
      element.getAttribute("aria-label"),
      element.getAttribute("title"),
      element.getAttribute("data-name"),
      element.getAttribute("data-field"),
      element.getAttribute("data-field-name"),
      element.getAttribute("data-testid"),
      element.getAttribute("data-test-id"),
      element.getAttribute("data-qa"),
      element.getAttribute("data-key"),
      element.getAttribute("data-repeatable-section"),
      element.getAttribute("data-repeatable-list"),
      element.getAttribute("data-repeatable-entry"),
      element.getAttribute("data-repeatable-type"),
      element.getAttribute("data-repeatable-index"),
      element.getAttribute("data-field-role"),
      element.getAttribute("data-add-section")
    ];

    const className = typeof element.className === "string" ? element.className : "";
    hints.push(className);
    return hints.filter(Boolean);
  }

  function inferLabelFromSemanticHints(element) {
    const hint = collectSemanticHints(element, "").find((item) => {
      const normalized = normalize(item);
      return /name|email|mail|phone|mobile|school|degree|gpa|github|linkedin|city|location|summary|intro|skill|姓名|邮箱|电话|手机|学校|学历|学位|城市|技能|介绍/.test(normalized);
    });
    return hint || "";
  }

  function findRepeatableType(element) {
    const entry = element.closest("[data-repeatable-entry], [data-repeatable-section], [data-repeatable-list]");
    if (!entry) {
      return "";
    }
    return entry.getAttribute("data-repeatable-entry")
      || entry.getAttribute("data-repeatable-section")
      || entry.getAttribute("data-repeatable-list")
      || "";
  }

  function findRepeatableIndex(element) {
    const entry = element.closest("[data-repeatable-index]");
    return entry ? entry.getAttribute("data-repeatable-index") || "" : "";
  }

  function findActionContext(element) {
    const section = element.closest("[data-repeatable-section], fieldset, section, form, .section, .form-section");
    const sectionLabel = section
      ? cleanupLabelText(section.getAttribute("data-repeatable-section") || section.querySelector("legend, h1, h2, h3, h4")?.textContent || "")
      : "";
    const nearby = cleanupLabelText([
      collectPreviousSiblingText(element),
      section ? getReadableText(section).slice(0, 120) : ""
    ].filter(Boolean).join(" "));
    return {
      section: sectionLabel,
      nearby_context: nearby
    };
  }

  function isPotentialAddButton(button) {
    const text = normalize([
      button.text,
      button.aria_label,
      button.title,
      button.section,
      button.nearby_context,
      button.semantic_hints
    ].filter(Boolean).join(" "));
    const addTokens = [
      "add",
      "new",
      "plus",
      "create",
      "append",
      "新增",
      "添加",
      "增加",
      "继续添加",
      "+"
    ];
    return addTokens.some((token) => text.includes(normalize(token)));
  }

  function isDangerousAction(button) {
    const text = normalize([
      button.text,
      button.aria_label,
      button.title,
      button.section,
      button.nearby_context,
      button.semantic_hints
    ].filter(Boolean).join(" "));
    const dangerousTokens = [
      "submit",
      "save",
      "next",
      "delete",
      "remove",
      "cancel",
      "back",
      "finish",
      "confirm",
      "提交",
      "保存",
      "下一步",
      "删除",
      "移除",
      "取消",
      "返回",
      "完成",
      "确认"
    ];
    return dangerousTokens.some((token) => text.includes(normalize(token)));
  }

  function isVisibleAction(element) {
    if (!element || element.disabled || element.getAttribute("aria-disabled") === "true") {
      return false;
    }
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none"
      && style.visibility !== "hidden"
      && rect.width > 0
      && rect.height > 0;
  }

  function collectAncestorElements(element, maxDepth) {
    const ancestors = [];
    let current = element.parentElement;
    let depth = 0;
    while (current && current !== document.body && depth < maxDepth) {
      ancestors.push(current);
      current = current.parentElement;
      depth += 1;
    }
    return ancestors;
  }

  function getTextBeforeElement(container, element) {
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (!node.textContent || !node.textContent.trim()) {
          return NodeFilter.FILTER_REJECT;
        }
        const parent = node.parentElement;
        if (!parent || isInsideFormControl(parent)) {
          return NodeFilter.FILTER_REJECT;
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    });

    const texts = [];
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const relation = node.compareDocumentPosition(element);
      if (relation & Node.DOCUMENT_POSITION_PRECEDING) {
        break;
      }
      texts.push(cleanupLabelText(node.textContent || ""));
    }

    return texts.filter(Boolean).slice(-3).join(" ");
  }

  function getReadableText(element) {
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (!node.textContent || !node.textContent.trim()) {
          return NodeFilter.FILTER_REJECT;
        }
        const parent = node.parentElement;
        if (!parent || isInsideFormControl(parent)) {
          return NodeFilter.FILTER_REJECT;
        }
        const style = window.getComputedStyle(parent);
        if (style.display === "none" || style.visibility === "hidden") {
          return NodeFilter.FILTER_REJECT;
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    });

    const texts = [];
    while (walker.nextNode() && texts.length < 8) {
      texts.push(cleanupLabelText(walker.currentNode.textContent || ""));
    }
    return texts.filter(Boolean).join(" ");
  }

  function isLikelyLabelText(text) {
    const cleaned = cleanupLabelText(text);
    if (!cleaned || cleaned.length > 80) {
      return false;
    }
    const rejected = ["请选择", "请输入", "please select", "please enter", "error", "invalid"];
    return !rejected.some((item) => normalize(cleaned).includes(item));
  }

  function extractOptions(element) {
    if (element.tagName.toLowerCase() !== "select") {
      return [];
    }
    return Array.from(element.options || []).map((option) => ({
      value: option.value,
      text: cleanupLabelText(option.textContent || ""),
      disabled: Boolean(option.disabled || option.parentElement?.tagName === "OPTGROUP" && option.parentElement.disabled)
    }));
  }

  function getCurrentValue(element) {
    if (element.tagName.toLowerCase() === "select") {
      return element.options[element.selectedIndex]?.textContent || element.value || "";
    }
    return element.value || "";
  }

  function getRawValue(element) {
    return element.value || "";
  }

  function getFieldType(element) {
    if (element.tagName.toLowerCase() === "select") {
      return "select";
    }
    if (element.tagName.toLowerCase() === "textarea") {
      return "textarea";
    }
    return element.getAttribute("type") || "text";
  }

  function isVisibleFormField(element) {
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none"
      && style.visibility !== "hidden"
      && rect.width > 0
      && rect.height > 0;
  }

  function isFormControl(element) {
    return element.matches?.("input, select, textarea, button") || false;
  }

  function isInsideFormControl(element) {
    return Boolean(element.closest("input, select, textarea, button, option, script, style, svg"));
  }

  function cleanupLabelText(value) {
    return String(value || "")
      .replace(/\*/g, "")
      .replace(/[\u200b-\u200f]/g, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function cleanupSemanticHint(value) {
    return String(value || "")
      .replace(/formily-item/gi, " ")
      .replace(/form item/gi, " ")
      .replace(/[.#>:[\]="'()]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function normalize(value) {
    return String(value || "")
      .toLowerCase()
      .replace(/[_\-:：/\\|()[\]{}.,，。;；]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function cssEscape(value) {
    if (window.CSS && typeof window.CSS.escape === "function") {
      return window.CSS.escape(value);
    }
    return String(value).replace(/["'\\#.:,[\]()>+~*=\s]/g, "\\$&");
  }

  function escapeAttribute(value) {
    return String(value).replace(/\\/g, "\\\\").replace(/"/g, "\\\"");
  }

  function hexToRgba(hex, alpha) {
    const normalized = hex.replace("#", "");
    const red = parseInt(normalized.slice(0, 2), 16);
    const green = parseInt(normalized.slice(2, 4), 16);
    const blue = parseInt(normalized.slice(4, 6), 16);
    return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
  }
})();
