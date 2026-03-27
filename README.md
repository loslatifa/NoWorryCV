# NoWorryCV

NoWorryCV 是一个基于 Python 的 JD 定制简历系统。它会把“原始简历 + 目标 JD”转成一份更贴合岗位、但仍然真实可追溯的简历版本，并返回匹配分析、修改说明、风险提示和等待中的 JD 知识点复习卡片。

## Features

- 支持上传 `PDF / DOCX / Markdown / TXT` 简历
- 支持输入目标 JD 和候选人补充备注
- 识别 `校招 / 社招 / 实习` 招聘类型
- 输出结构化 `candidate_profile`、`jd_profile`、`gap_analysis`、`rewrite_strategy`
- 生成 ATS 友好的 Markdown 简历
- 执行真实性审查、ATS 评分和 critic 迭代优化
- 前端展示真实任务进度
- 等待期间根据 JD 生成可手动切换的知识点复习卡片

## Tech Stack

- Backend: `FastAPI`
- Agent orchestration: `LangGraph`
- Schema validation: `Pydantic`
- LLM provider: `Qwen / OpenAI-compatible / stub fallback`
- Frontend: 内置静态页面，由 FastAPI 托管

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install ".[dev]"
cp .env.example .env
```

编辑 `.env`，填入你自己的 key，然后启动服务：

```bash
PYTHONPATH=. uvicorn backend.app.main:app --reload
```

打开：

```text
http://127.0.0.1:8000/app/
```

## Environment Variables

默认使用 `stub` provider，不依赖真实模型也能跑通最小闭环：

```env
LLM_PROVIDER=stub
PROMPT_VERSION=v1
```

如果要接 Qwen：

```env
LLM_PROVIDER=qwen
QWEN_API_KEY=your_qwen_api_key
QWEN_MODEL=qwen-plus
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

也兼容 DashScope 常见命名：

```env
DASHSCOPE_API_KEY=your_qwen_api_key
QWEN_MODEL=qwen-plus
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

可选项：

```env
LLM_RESPONSE_FORMAT=json_object
LLM_TIMEOUT_SECONDS=45
LLM_MAX_RETRIES=2
```

## Main Endpoints

- `GET /health`
- `POST /api/v1/resume/parse`
- `POST /api/v1/jd/analyze`
- `POST /api/v1/tailor-runs`
- `POST /api/v1/tailor-runs/upload`
- `POST /api/v1/tailor-runs/upload-jobs`
- `GET /api/v1/tailor-runs/{run_id}/status`

网页端使用的是 `upload-jobs -> status` 的异步模式。

## Local Testing

运行后端测试：

```bash
PYTHONPATH=. pytest backend/tests -q
```

验证 Qwen 连通性：

```bash
source .venv/bin/activate
PYTHONPATH=. python scripts/check_qwen.py
```

检查公开仓库文件里是否包含疑似密钥：

```bash
PYTHONPATH=. python scripts/check_public_secrets.py
```

## GitHub Upload Safety

这个项目已经忽略了常见本地密钥文件：

- `.env`
- `.env.*`
- `!.env.example`
- `*.pem`
- `*.key`
- `*.p12`
- `*.pfx`
- `*.crt`

上传前请确认：

1. 只提交 `.env.example`，不要提交 `.env`
2. 不要把真实 key 写进 `README.md`、`.env.example`、`docs/` 或脚本
3. 先运行一次 `python scripts/check_public_secrets.py`
4. 如果你用的是 GitHub 网页手动上传，不要把 `.env` 文件选进去

## Project Structure

```text
backend/
  app/
    agents/
    api/
    core/
    graph/
    schemas/
    services/
    static/
  tests/
docs/
prompts/
scripts/
```

## Docs

- [Resume Quality Improvement Prompt](docs/resume_quality_improvement_prompt.md)

## Current Limitations

- 当前仍以 MVP 为主，数据库持久化尚未接入
- PDF / DOCX 解析依赖文本质量，扫描件效果有限
- 结果质量仍然高度依赖原始简历质量和 JD 完整度

## License

如需公开仓库，请按你的实际使用场景补充许可证。
