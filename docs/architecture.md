# NoWorryCV Architecture

当前工程按 Python-first MVP 设计，重点是先把“解析 -> 分析 -> 策略 -> 改写 -> 审查 -> 输出”的闭环跑通。

## 核心模块

- `backend/app/api`: FastAPI 路由层
- `backend/app/schemas`: 所有结构化输入输出契约
- `backend/app/agents`: 多 agent 逻辑
- `backend/app/graph`: 流程编排入口
- `backend/app/services`: 文件解析、LLM 接口、评分工具

## 当前状态

- 解析和生成先采用启发式实现，便于快速验证产品闭环
- 结构上已为真实 LLM 接入留出 Provider 和 Prompt 扩展点
- 审查逻辑默认以“真实性优先”作为强约束

## 下一阶段建议

1. 把每个 agent 的 prompt 独立为模板文件，并引入版本管理
2. 用 LangGraph 的 `StateGraph` 替换串行 orchestrator，实现更清晰的路由和 retry
3. 接入数据库，持久化 `tailor_runs`, `resume_versions`, `review_reports`
4. 加强 PDF / DOCX 解析与 traceability 的 source span 精度
