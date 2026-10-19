const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const context = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, "../form_controls.js"), "utf8"), context);
const { prepareValue, selectOption } = context.NoWorryCVFormControls;
const option = (value, text, disabled = false) => ({ value, text, disabled });

test("native date and month accept unambiguous confirmed dates", () => {
  assert.equal(prepareValue({ type: "month" }, "2024年6月").value, "2024-06");
  assert.equal(prepareValue({ type: "month" }, "2024/6/15").value, "2024-06");
  assert.equal(prepareValue({ type: "date" }, "2024.2.29").value, "2024-02-29");
});

test("missing precision, present, ambiguous dates and impossible dates require review", () => {
  for (const [type, value] of [["date", "2024-06"], ["month", "2024"], ["month", "present"],
    ["date", "06/07/2024"], ["date", "2023-02-29"], ["date", "2024-04-31"], ["month", "2024-00"]]) {
    const result = prepareValue({ type }, value);
    assert.equal(result.value, "", `${type}: ${value}`);
    assert.ok(result.reason);
  }
});

test("native date bounds are checked before filling", () => {
  assert.ok(prepareValue({ type: "month", min: "2024-07" }, "2024-06").reason);
  assert.ok(prepareValue({ type: "date", max: "2024-06-01" }, "2024-06-02").reason);
});

test("split year and month fields derive only known date components", () => {
  assert.equal(prepareValue({ label: "开始年份" }, "2024-06").value, "2024");
  assert.equal(prepareValue({ name: "start_month", type: "number" }, "2024-06").value, "6");
  assert.equal(prepareValue({ label: "Start month" }, "2024-06").value, "06");
  assert.ok(prepareValue({ date_part: "day" }, "2024-06").reason);
  assert.ok(prepareValue({ date_part: "month" }, "2024").reason);
});

test("month labels override zero-based option values", () => {
  const field = { type: "select", date_part: "month", options: [option("0", "January"), option("1", "February"), option("5", "June")] };
  const result = prepareValue(field, "2024-06");
  assert.equal(result.value, "June");
  assert.equal(result.option_value, "5");
  assert.equal(selectOption(field, result.value).value, "5");
});

test("numeric month labels match without selecting an opaque conflicting value", () => {
  const field = { type: "select", date_part: "month", options: [option("6", "5月"), option("7", "6月")] };
  assert.equal(prepareValue(field, "2024-06").option_value, "7");
  assert.equal(selectOption({ date_part: "month", options: [option("06", "July")] }, "06"), null);
});

test("select matching rejects partial, duplicate, disabled and empty options", () => {
  assert.equal(selectOption({ options: [option("1", "北京海淀"), option("2", "北京朝阳")] }, "北京"), null);
  assert.equal(selectOption({ options: [option("1", "北京"), option("2", "北京")] }, "北京"), null);
  assert.equal(selectOption({ options: [option("1", "北京", true)] }, "北京"), null);
  assert.equal(selectOption({ options: [option("", "请选择")] }, "请选择"), null);
  assert.equal(selectOption({ multiple: true, options: [option("1", "北京")] }, "北京"), null);
});

test("degree aliases require a unique option and never guess study subject", () => {
  assert.equal(selectOption({ options: [option("B", "Bachelor's degree"), option("M", "Master's degree")] }, "本科").value, "B");
  assert.equal(selectOption({ options: [option("B", "本科"), option("B2", "学士")] }, "Bachelor"), null);
  assert.equal(selectOption({ options: [option("BA", "Bachelor of Arts")] }, "Bachelor of Science"), null);
});
