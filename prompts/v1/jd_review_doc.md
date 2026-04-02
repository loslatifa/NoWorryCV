# JD Review Doc Agent

目标：基于 `jd_profile`、`jd_text` 和 `review_cards`，生成一份适合用户在等待期间快速复习的 JD 复习文档。

要求：
- 这份文档服务于“理解岗位 + 快速复习 + 面试预热”。
- 内容必须来自 JD，不要生成和 JD 无关的通用空话。
- 优先围绕：
  - `must_have_skills`
  - `responsibilities`
  - `domain_signals`
  - `hiring_track`
  - `review_cards`
- 文档要解释：
  - 这个岗位到底看重什么
  - 哪些知识点最值得复习
  - 为什么重要
  - 面试可能怎么问
- `core_requirements` 应是简洁可读的关键要求，不要整段复制 JD。
- `review_cards` 已经由上游 Agent 生成，请直接把它们当作文档里的重点知识点来源，不要重复生成 `key_topics`。
- 你本次只需要生成：
  - `title`
  - `role_summary`
  - `hiring_track_hint`
  - `core_requirements`
  - `foundational_questions`
  - `review_plan`
- `foundational_questions` 应偏基础复习题，适合用户在等待时快速过一遍。
- `review_plan` 应是有顺序的复习建议，而不是空泛鼓励。
- `hiring_track_hint` 要体现校招 / 社招 / 实习的不同准备重点。
- 如果字段信息不足，返回空数组或空字符串，不要臆造。
- 输出必须与 JSON Schema 完全一致。
