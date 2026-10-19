/* Shared by the service worker and the page's isolated content-script world. */
(function installFormControls() {
  const clean = value => String(value ?? "").normalize("NFKC").trim().toLowerCase().replace(/\s+/g, " ");
  const months = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"];
  const degreeGroups = [
    ["本科", "学士", "学士学位", "bachelor", "bachelors", "bachelor's", "bachelor's degree", "bachelors degree", "undergraduate"],
    ["硕士", "硕士学位", "master", "masters", "master's", "master's degree", "masters degree"],
    ["博士", "博士学位", "phd", "ph.d.", "doctorate", "doctoral"]
  ];

  function parseDate(value) {
    const text = clean(value);
    const match = text.match(/^(\d{4})(?:[-/.](\d{1,2})(?:[-/.](\d{1,2}))?|年(?:(\d{1,2})月(?:(\d{1,2})日)?)?)?$/);
    if (!match) return null;
    const year = Number(match[1]);
    const month = Number(match[2] || match[4]) || null;
    const day = Number(match[3] || match[5]) || null;
    if (!year || (match[2] || match[4]) && (!month || month > 12)) return null;
    if (match[3] || match[5]) {
      const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
      const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
      if (!day || day > days[month - 1]) return null;
    }
    return { year: String(year).padStart(4, "0"), month: month && String(month).padStart(2, "0"), day: day && String(day).padStart(2, "0") };
  }

  function datePart(field) {
    if (["year", "month", "day"].includes(field.date_part)) return field.date_part;
    const text = clean([field.label, field.name, field.id, field.field_role].filter(Boolean).join(" "));
    const parts = [
      ["year", /(?:\byear\b|_year\b|year_|年份|年度|年$)/],
      ["month", /(?:\bmonth\b|_month\b|month_|月份|月$)/],
      ["day", /(?:\bday\b|_day\b|day_|日$)/]
    ].filter(([, pattern]) => pattern.test(text));
    return parts.length === 1 ? parts[0][0] : "";
  }

  function component(value, part) {
    const text = clean(value);
    if (part === "month") {
      const index = months.findIndex(month => text === month || text === month.slice(0, 3));
      if (index >= 0) return String(index + 1).padStart(2, "0");
    }
    const match = text.match(part === "year" ? /^(\d{4})年?$/ : part === "month" ? /^(\d{1,2})月?$/ : /^(\d{1,2})日?$/);
    if (!match) return null;
    const number = Number(match[1]);
    if (!number || number > (part === "year" ? 9999 : part === "month" ? 12 : 31)) return null;
    return String(number).padStart(part === "year" ? 4 : 2, "0");
  }

  function selectOption(field, value) {
    if (field.multiple) return null;
    const options = (field.options || []).filter(option => !option.disabled && String(option.value ?? "") !== "");
    const target = clean(value);
    if (!target) return null;
    const part = datePart(field);
    const dateValue = part && component(value, part);
    // Visible month names take precedence over opaque, sometimes zero-based values.
    const dated = dateValue && options.filter(option => component(option.text, part) === dateValue);
    if (dateValue) return dated.length === 1 ? dated[0] : null;
    const exact = options.filter(option => clean(option.value) === target || clean(option.text) === target);
    if (exact.length) return exact.length === 1 ? exact[0] : null;
    const aliases = degreeGroups.find(group => group.includes(target));
    if (!aliases) return null;
    const matching = options.filter(option => aliases.includes(clean(option.text)) || aliases.includes(clean(option.value)));
    return matching.length === 1 ? matching[0] : null;
  }

  function prepareValue(field, rawValue) {
    let value = String(rawValue ?? "").trim();
    const type = field.type || field.tag || "text";
    const part = datePart(field);
    const fail = reason => ({ value: "", reason });
    if (!value) return fail("没有已确认的资料，请手动补充。");
    if (["checkbox", "radio", "password"].includes(type)) return fail("此类控件需手动处理。");
    if (type === "date" || type === "month") {
      const date = parseDate(value);
      if (!date?.month || type === "date" && !date.day) return fail("资料的日期精度不足或日期无效，请手动核实；不会补造月份或日期。");
      value = `${date.year}-${date.month}` + (type === "date" ? `-${date.day}` : "");
      if (field.min && value < field.min || field.max && value > field.max) return fail("已确认日期超出控件允许范围，请手动核实。");
    } else if (part) {
      const date = parseDate(value);
      value = date?.[part] || component(value, part);
      if (!value) return fail("资料缺少此日期分量或格式不明确，请手动核实。");
      if (type === "number") value = String(Number(value));
    }
    if (type === "select" || field.tag === "select") {
      const option = selectOption(field, value);
      if (!option) return fail("没有唯一且可用的匹配选项，请手动选择。");
      return { value: String(option.text || option.value), option_value: String(option.value), reason: "" };
    }
    return { value, reason: "" };
  }

  globalThis.NoWorryCVFormControls = { parseDate, datePart, selectOption, prepareValue };
})();
