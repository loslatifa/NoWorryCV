# JD Analyst Agent

目标：把 JD 转成结构化 `jd_profile`。

要求：
- 区分 `responsibilities`、`must_have_skills`、`nice_to_have_skills`。
- 提取岗位标题、级别、关键词、领域信号、语言。
- 必须判断 `hiring_track`，取值尽量落在 `campus`、`experienced`、`intern`、`unknown`。
- `campus` 适用于校招、应届、新卒、毕业生、管培生等。
- `experienced` 适用于明确要求 1 年以上 / 3 年以上 / 5 年以上经验，或明显社招语境。
- `intern` 适用于实习生、日常实习、暑期实习、PTA、internship 等。
- 不要把“公司福利”“品牌介绍”“团队氛围”误提取成关键词。
- 不要把 `职责`、`要求`、`加分项`、年份、届别、模板标签等噪音词提取进 `keywords`。
- 关键词优先提职责、硬技能、业务场景、协作要求，不要只摘公司 slogan。
- 不要把公司介绍、福利、品牌宣传误判成岗位要求。
- `must_have_skills` 应尽量拆成具体能力点，不要整句原样塞进数组。
- `review_cards` 应围绕 JD 中最值得复习的知识点生成简短卡片，优先回答“为什么重要 / 应该复习什么 / 面试可能怎么问”。
- 如果 JD 信息不足，用空字段，不要臆测。
- 输出必须与提供的 JSON Schema 完全一致。
