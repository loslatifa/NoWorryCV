const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const context = vm.createContext({ chrome: { runtime: { onMessage: { addListener() {} } } } });
vm.runInContext(fs.readFileSync(require("node:path").join(__dirname, "../form_engine.js"), "utf8"), context);
const resume = { personal_info: { name: "李明", email: "liming@example.com" }, skills: ["SQL"],
  projects: [{ name: "数据看板", role: "开发者", description: "使用 SQL 开发数据看板" }] };
const field = (selector, label, extra = {}) => ({ selector, label, type: "text", tag: "input", ...extra });

test("confirmed resume maps basics and rewritten project description", () => {
  const mappings = context.mapFields([
    field("#name", "姓名"), field("#email", "邮箱"),
    field("#project", "项目描述", { repeatable_type: "projects", repeatable_index: "0", field_role: "description" })
  ], resume);
  assert.equal(mappings[0].fill_value, "李明");
  assert.equal(mappings[1].fill_value, "liming@example.com");
  assert.equal(mappings[2].fill_value, "使用 SQL 开发数据看板");
});

test("missing answers stay disabled and are not invented", () => {
  const preview = context.buildFillPreview([field("#salary", "期望薪资"), field("#phone", "电话")], resume);
  assert.ok(preview.items.every(item => !item.enabled));
  assert.ok(preview.items.every(item => !item.fill_value));
});

test("neighboring project and contact text cannot override direct labels", () => {
  const noise = { dom_context: "姓名 邮箱 电话 项目名称 项目角色 项目描述", semantic_hints: "projects project name phone" };
  const preview = context.buildFillPreview([
    field("#full-name", "姓名", noise), field("#intro", "自我介绍", noise), field("#salary", "期望薪资", noise)
  ], { ...resume, summary: "真实项目经历摘要" });
  assert.equal(preview.items[0].fill_value, "李明");
  assert.equal(preview.items[1].fill_value, "真实项目经历摘要");
  assert.equal(preview.items[2].fill_value, "");
  assert.equal(preview.items[2].enabled, false);
});

test("planner exposes missing repeatable groups with no unsafe add action", () => {
  const plan = context.planForm([], [], resume);
  const projects = plan.repeatable_sections.find(item => item.type === "projects");
  assert.equal(projects.missing_group_count, 1);
  assert.equal(projects.add_button_selector, null);
  assert.ok(plan.warnings.length);
});
