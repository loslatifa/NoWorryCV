# NoWorryCV

由网页工作台和 Chrome 插件组成的本地求职助手：上传简历、粘贴岗位描述（JD），生成可编辑、可溯源的定制简历，并在确认后辅助填写申请表。

```text
上传简历 → 核对完整经历 → 按 JD 定制 → 编辑与导出 → 确认后填写
```

## 主要功能

- **资料与简历**：整段经历编辑、档案复用、岗位定制、事实溯源及匹配参考分。
- **编辑与导出**：React + TypeScript 编辑器、撤销重做、局部重写、版本恢复、20 款版式及 PDF / DOCX 导出。
- **求职准备**：求职信、自我介绍、项目讲稿、HR 话术和互动模拟面试。
- **投递管理**：Chrome 侧栏填写预览、投递快照、职位阶段与下一步行动。

## 快速开始

需要 Python 3.9+、Node.js 22；使用插件需要 Chrome 116+。

### 1. 安装依赖并构建编辑器

在仓库根目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
npm --prefix frontend ci
npm --prefix frontend run build
```

### 2. 配置模型

首次配置时复制模板；已有 `.env` 时直接编辑：

```bash
cp .env.example .env
```

默认使用 DeepSeek，在 `.env` 填写 `DEEPSEEK_API_KEY`。Qwen、其他兼容服务及完整参数见 [.env.example](.env.example)。修改配置后重启后端。

只体验流程时可设置 `LLM_PROVIDER=stub`、`LLM_STRICT_MODE=false`，使用演示模式。

### 3. 启动工作台

```bash
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

打开 [网页工作台](http://127.0.0.1:8000/app/)，上传简历并填写 JD。生成后点击「在编辑器中打开」，使用独立编辑器。

| 入口 | 地址 |
| --- | --- |
| 网页工作台 | <http://127.0.0.1:8000/app/> |
| 职位投递工作台 | <http://127.0.0.1:8000/app/positions.html> |
| API 文档 | <http://127.0.0.1:8000/docs> |

### 4. 加载插件（可选）

打开 `chrome://extensions`，开启开发者模式，加载本仓库的 `extension/` 目录。插件服务地址需与网页一致；详细操作见 [插件说明](extension/README.md)。

## 开发与部署

FastAPI + LangGraph 提供生成流程，网页通过 SSE 接收进度，断线后降级为轮询。任务与草稿默认使用 JSON / SQLite，可通过 `DATABASE_URL` 切换到 PostgreSQL；当前 PostgreSQL 模式限单应用进程。

```bash
python -m pytest -q
node --test backend/tests/js/*.cjs extension/tests/*.test.cjs
```

Docker 配置已提供，镜像构建与容器运行验收尚待完成。编辑器开发、数据库迁移及 Docker 启动方式见 [开发与部署说明](docs/development.md)。

## 使用说明与文档

简历和相关材料会发送至配置的模型服务。生成任务默认保留 24 小时；长期档案需明确同意保存。访问凭据保存在当前浏览器，最终投递由用户手动提交。匹配分仅供参考，不代表录用或 ATS 通过概率。

- [使用说明](docs/usage.md)：资料核对、模板、求职材料、模拟面试、数据保存与支持范围。
- [开发与部署](docs/development.md)：模型配置、编辑器开发、PostgreSQL、SSE、Docker 与验证。
- [质量评测](evals/README.md)：评测集、指标和真实模型验证记录。
- [功能清单](feature_list.json) · [技术栈升级计划](docs/minimal-stack-upgrade-plan.md)
