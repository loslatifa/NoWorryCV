# 开发与部署

[返回项目首页](../README.md) · [技术栈升级计划](minimal-stack-upgrade-plan.md)

## 模型配置与解析排查

首次配置时复制模板；已有 `.env` 时直接编辑现有文件。

```bash
cp .env.example .env
```

模板默认使用 DeepSeek 官方接口。在 `.env` 中填写 DeepSeek 自己的 API key：

```dotenv
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-flash
DEEPSEEK_API_KEY=your_deepseek_api_key
LLM_RESPONSE_FORMAT=json_object
```

DeepSeek 请求默认关闭思考模式，使用 JSON 输出并由服务端校验结构；模型名按 [DeepSeek 官方文档](https://api-docs.deepseek.com/) 使用 `deepseek-flash`。`DEEPSEEK_API_KEY` 仅在地址为 `api.deepseek.com` 时使用；也可显式填写 `LLM_API_KEY`，其优先级更高。

仍支持 Qwen：设置 `LLM_PROVIDER=qwen`，填写 `QWEN_API_KEY`、`QWEN_MODEL` 和 `QWEN_BASE_URL`。其他兼容接口使用 `LLM_PROVIDER=openai_compatible`，填写 `LLM_API_KEY`、`LLM_MODEL` 和 `LLM_BASE_URL`。更换服务时应使用对应服务商的密钥；修改 `.env` 后重启后端生效。完整配置项见 [.env.example](../.env.example)。

解析时出现 503，页面会说明失败环节及密钥、额度、超时、限流或输出校验问题；终端记录对应的 `code` 和错误类型，不输出模型原始错误或简历内容。解析输出默认预留 4096 tokens，服务明确报告长度截断时会增加预算重试（最高 8192）；字段格式错误会附带校验要求自动重试。重试仍失败时保留错误，不以演示数据替代真实解析。排查时可提供错误类别、文件格式与页数，无需分享密钥或简历正文。

## React 编辑器

需要 Node.js 22。首次使用或修改前端源码后，在仓库根目录执行：

```bash
npm --prefix frontend ci
npm --prefix frontend run build
```

完成生成后，在结果页点击「在编辑器中打开」。独立页面位于 `/app/editor/?run=<任务 ID>`，支持整段经历编辑、撤销与重做、保存版本、刷新匹配分、差异对照、局部重写及历史版本恢复。访问凭据沿用当前浏览器的任务历史、会话或档案凭据，不写入 URL。

开发时可运行 `npm --prefix frontend run watch`，继续从 `http://127.0.0.1:8000` 访问新旧页面，共享本地凭据。`npm --prefix frontend run dev` 提供独立 Vite 服务及 API 代理，但不同端口的浏览器存储不共享；应在同一来源准备联调凭据。

API 类型由后端 Schema 生成，修改 API 后执行并保留生成文件：

```bash
python -m scripts.generate_openapi
npm --prefix frontend run types
npm --prefix frontend run build
```

## PostgreSQL 与任务进度

不配置 `DATABASE_URL` 时，任务记录及草稿版本继续保存在 JSON 文件，队列继续使用 SQLite。配置后，两者切换到 PostgreSQL；其余六个业务库继续使用 `.dist` 下的 SQLite 文件。

```dotenv
DATABASE_URL=postgresql://用户:密码@127.0.0.1:5432/noworrycv
```

首版 PostgreSQL 模式只支持一个应用进程，可运行多个线程任务 worker；请勿增加 Uvicorn `--workers` 或部署多个应用副本。数据库会话锁会拒绝第二个任务存储实例。任务记录按变化增量写入，保留凭据哈希、过期时间、完整草稿版本、阶段记录和检查点。没有自动切换现有数据的操作。

如需迁移已有记录，先停止旧应用，备份 JSON 任务文件、队列 SQLite 文件及六个业务库，然后将源文件副本导入**空的 PostgreSQL 数据库**：

```bash
python -m scripts.migrate_run_storage \
  --run-store /备份路径/run_store.json \
  --task-queue /备份路径/task_queue.sqlite3
```

命令从 `DATABASE_URL` 读取目标地址，源文件只读、导入整体事务提交；目标非空或应用仍在运行时拒绝导入。保留源任务 ID、token 哈希和检查点，原浏览器凭据可继续使用。六个业务库需随部署一并保留；切换环境的主机名或端口后，浏览器本地凭据也需按原来源访问或恢复。

网页进度优先使用带 `X-Run-Token` 的 SSE 事件流 `/api/v1/tailor-runs/{id}/events`；断线时自动退回原有 `/status` 轮询。插件仍使用原接口。事件为完整状态快照，任务结束后关闭连接，断线后可直接取得最新状态。

存储与 SSE 回归可通过 `python -m pytest -q` 运行。PostgreSQL 集成测试仅在设置 `TEST_DATABASE_URL` 时运行，每项使用独立临时 schema；请指定专用测试数据库，并确保测试用户有创建 schema 的权限。该地址与应用实际使用的 `DATABASE_URL` 分开配置。

## Docker Compose

启动 Docker Desktop，配置 `.env` 中的模型服务后运行：

```bash
docker compose up -d --build
```

默认地址仍为 `http://127.0.0.1:8000/app/`。端口冲突时可在 `.env` 设置 `APP_PORT=8001`，并同步调整插件后端地址。Compose 启动 PostgreSQL 16 和单进程应用，以数据库健康状态控制启动顺序。镜像包含编辑器构建产物及中文字体，应用以非 root 用户运行。如需使用 stub 演示模式，请在 `.env` 中显式设置 `LLM_PROVIDER=stub` 和 `LLM_STRICT_MODE=false`。

PostgreSQL 和其余 SQLite 数据分别保存在 `postgres_data` 与 `app_data` 命名卷；应用重启不会删除它们。Compose 默认使用本地开发数据库口令，可通过 `POSTGRES_PASSWORD` 设置仅含字母和数字的新口令；已有数据库卷的口令变更需同时更新数据库用户。

```bash
docker compose restart app
docker compose logs --tail=50 app
```

Docker 镜像构建、容器内生成、中文导出和容器重启持久化验收暂待 Docker 环境就绪；配置检查不等于容器运行验收。

## 开发与验证

项目使用 FastAPI 提供接口，LangGraph 编排生成与审查流程；任务与草稿默认使用 JSON / SQLite，也可切换为 PostgreSQL，其余业务库使用 SQLite。插件采用 Manifest V3，整合了 JobAutoAgent 初版的表单识别与填写引擎。

```text
backend/app/       接口、生成流程、数据存储和网页工作台
backend/tests/     后端测试
frontend/          React + TypeScript 独立编辑器
extension/         Chrome 侧栏、页面识别和填写引擎
prompts/v1/        各生成与审查阶段的提示词
evals/             合成评测集、回归指标说明
feature_list.json  功能清单、完成状态和后续规划
```

运行验证：

```bash
python -m pytest -q
node --test backend/tests/js/*.cjs extension/tests/*.test.cjs
python scripts/evaluate_quality.py --provider stub
```

后端测试使用 stub 模型验证流程，不调用真实模型。插件的本地模拟投递页与手动验收步骤见 [插件说明](../extension/README.md#验证)。功能状态与后续规划见 [功能清单](../feature_list.json)。

结果页支持评价整份已保存版本或单条修改；「反馈与质量概览」可以按招聘类型和语言查看当前保存期内的指标。模型与提示词升级的基线对照、指标定义和评测集维护规则见 [质量评测说明](../evals/README.md)。

2026-10-15 已切换到 DeepSeek 官方 `deepseek-flash`，连通性和 JSON 输出通过，引用修复后的四个合成样例真实模型回归全部通过，与已有基线相比无回退。详细指标和验证边界见 [DeepSeek 验证记录](../evals/reports/2026-10-15-deepseek-flash.md)；此前 Qwen 的失败记录见 [早期验证记录](../evals/reports/2026-10-15.md)。

求职材料包与模拟面试也已完成一轮 DeepSeek 合成样例验收：中英文材料包及八个面试场景共 10/10 通过，146 个检查通过，未发现基线回退。复现命令与验证边界见 [准备材料验收报告](../evals/reports/2026-10-15-deepseek-preparation.md)。
