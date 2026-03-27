# Resume Quality Improvement Prompt

你正在优化 NoWorryCV 的下一轮质量，而不是只让输出“看起来更像简历”。

本轮改进目标：

1. 先修结构化抽取，再谈文案润色
- 不允许把 Markdown 标题、`Resume/CV`、`职责/要求/加分项`、年份标签当成真实候选人信息或 JD 关键词。
- 先把候选人姓名、项目、教育、技能和 JD 要求抽对，再让 rewrite 去组织表达。

2. 严格区分校招 / 社招 / 实习
- `campus`：教育、项目、课程、竞赛、实习优先。
- `experienced`：工作经历、职责范围、量化结果、ownership 优先。
- `intern`：基础能力、项目实践、快速上手信号优先。
- 任何招聘类型都不能被写成另一种口吻。

3. summary 必须像候选人摘要，不要像系统说明
- 不要写“当前以校招视角整理”“已按岗位需求重排”这类元叙事句子。
- summary 应该是“候选人具备什么、做过什么、为什么匹配这个岗位”。
- summary 只能使用可验证事实。

4. 技能和关键词必须可读、可投递
- `A/B Testing` 不能被拆成 `A` 和 `B Testing`。
- `SQL`、`Tableau`、`Power BI` 等要统一成规范显示形式。
- JD 关键词中不应出现 `2026`、`职责`、`要求`、`岗位职责` 这类噪音词。

5. 等待中的复习卡片必须来自 JD 本身
- 卡片内容要基于 JD 中明确提到的技能、方法、业务场景和协作要求。
- 优先生成“为什么重要 / 复习什么 / 面试可能怎么问”三段式内容。
- 用户应该可以自己切换到下一个知识点，而不是被自动轮播打断。

本轮执行原则：
- 优先修 parser、JD analyst、skills normalization、keyword cleaning。
- 再修 waiting panel 的知识点卡片生成与交互。
- 最后再修 rewrite fallback 的 summary 和表达质量。
