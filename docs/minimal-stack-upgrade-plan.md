# NoWorryCV 技术栈补齐方案（最小实现）

更新日期：2026-10-19

## 目标

让简历中 NoWorryCV 的技术描述与代码一致，补齐 React、PostgreSQL、SSE、Docker 四项。原则是**只做简历原话需要的部分**，其余保持不动。

| 简历描述 | 当前实现 | 本方案的补齐范围 |
| --- | --- | --- |
| React + TypeScript 构建结构化编辑器 | 原生 HTML/JS（`backend/app/static`） | 编辑器做成独立的 React + TS 页面，其他页面不动 |
| 任务与草稿版本持久化至 PostgreSQL | 任务队列用 SQLite，草稿库是 `.dist/run_store.json` | 任务队列和草稿库支持 Postgres，另外 6 个存储继续用 SQLite |
| 长链路生成经 SSE 推送进度 | 前端 `pollTimer` 轮询 `/status` | 新增 SSE 接口，`/status` 轮询保留作为降级 |
| Docker Compose 一键部署 | 无 Docker 配置 | 一个 Dockerfile 加一个 compose 文件，起应用和 Postgres |

## 兼容约束

- 后端已有 API 路径不变。
- 插件依赖的地址不变：`/app/`、`/app/?run=&profile=`、`/app/positions.html`。
- 浏览器存储的凭据沿用 `noworrycv-run-history`、`noworrycv-candidate-archives`，新旧页面共享。
- 未设置 `DATABASE_URL` 时行为与现在完全一致，任务库 JSON 与队列 SQLite 仍是本地默认。
- 现有 313 项后端测试保持全部通过。

## 前提

- Mac 上安装 Docker Desktop，用于运行 Postgres 和验证 compose。
- 先保存包含未提交文件的工作快照，再新建 git 分支开发；切分支本身不隔离未提交文件。

---

## 1. PostgreSQL：任务队列 + 草稿库

### 草稿库（`backend/app/services/runs/store.py`）

- 草稿版本存在 `job.result.draft_versions` 中，整条任务记录存成一行 JSONB 即可。
- 新增 `PostgresRunStore`，继承 `PersistentRunStore`，复用现有业务方法，扩展 `_load` 和 `_persist_locked`；首版限定一个应用进程，通过数据库会话锁阻止第二个写入实例。
- 表结构：

  ```sql
  CREATE TABLE IF NOT EXISTS tailor_runs (
      run_id      TEXT PRIMARY KEY,
      payload     JSONB NOT NULL,
      token_hash  TEXT,
      expires_at  TIMESTAMPTZ NOT NULL,
      updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
  );
  CREATE INDEX IF NOT EXISTS idx_tailor_runs_expires ON tailor_runs (expires_at);
  ```

- 现在每次保存都整体重写所有任务。改成按每条任务 JSON 的内容哈希判断，只 upsert 有变化的行，并只删除本实例明确移除的已加载任务 ID，不能依据全局内存快照删除其他记录。

### 任务队列（`backend/app/services/runs/queue.py`）

- 新增兼容层 `PgCompatConnection`（建议放在 `backend/app/services/db/pg_compat.py`）：
  - 把 `?` 占位符转成 `%s`；
  - 将 `BEGIN IMMEDIATE` 映射为真实 `BEGIN`，保留 `COMMIT` / `ROLLBACK`，关闭连接时回滚未完成事务；仅忽略 SQLite 专属 `PRAGMA`；
  - 行数据以字典返回，兼容现有的 `row["field"]` 写法；
  - 主键冲突统一抛成 `IntegrityError`，现有的幂等提交逻辑不用改。
- `_claim_next` 领取任务的查询在 Postgres 下改为：

  ```sql
  UPDATE tasks
  SET status = 'running', attempt = attempt + 1, current_stage = next_stage, updated_at = %s
  WHERE run_id = (
      SELECT run_id FROM tasks
      WHERE status = 'queued' AND cancel_requested = 0
        AND attempt < max_attempts AND expires_at > %s
      ORDER BY created_at
      FOR UPDATE SKIP LOCKED
      LIMIT 1
  )
  RETURNING *;
  ```

- 建表改成 Postgres 版的 `CREATE TABLE IF NOT EXISTS`，`AUTOINCREMENT` 换成 `BIGSERIAL`。

### 切换方式

- `get_run_store()` 和 `get_task_queue()` 检查环境变量 `DATABASE_URL`：设置了用 Postgres 实现，否则保持 SQLite。
- `pyproject.toml` 新增依赖 `psycopg[binary]`；`.env.example` 增加 `DATABASE_URL` 说明。

### 验收

- 不设 `DATABASE_URL`：`python -m pytest -q` 全部通过。
- 新增 Postgres 冒烟测试，设置 `TEST_DATABASE_URL` 时才运行：提交任务 → 模拟中途重启 → 从断点恢复 → 保存草稿版本 → 重新加载后数据还在。

---

## 2. SSE 推送进度

### 后端（`backend/app/api/v1/routes.py`）

新增 `GET /api/v1/tailor-runs/{run_id}/events`：

- 鉴权与 `/status` 一致，读 `X-Run-Token` 请求头，无权限返回 404。
- 返回 `StreamingResponse`，`media_type="text/event-stream"`。
- 每 0.5 秒读一次任务状态，有变化就推一个状态快照事件，带递增 `id`：

  ```text
  id: 7
  event: status
  data: {"status": "running", "current_stage": "review", "progress_percent": 86, ...}
  ```

- 每 15 秒发一次心跳注释 `: ping`。
- 任务进入终态（completed / failed / cancelled）后发 `event: end` 并关闭连接。
- 响应头：`Cache-Control: no-cache`、`X-Accel-Buffering: no`。
- 每个事件都是完整快照，断线重连后直接推最新状态即可，不需要事件表。

### 前端（`backend/app/static/app.js`）

- 把 `pollTimer` 轮询换成 `fetch` + `ReadableStream` 读事件流，照常带 `X-Run-Token` 请求头。
- 不使用浏览器原生 `EventSource`：它不能带自定义请求头，而 token 不应放进 URL（会进访问日志）。
- 事件流失败时退回原来的轮询逻辑；插件继续使用 `/status`。

### 验收

用 TestClient 读事件流：能收到进度事件和 `end` 事件；无权限时返回 404。

---

## 3. React + TypeScript 编辑器

### 工程

- 新建 `frontend/`：Vite + React + TypeScript。
- `vite.config.ts` 中 `base: "/app/editor/"`，构建输出到 `backend/app/static/editor/`。现有的 `/app` 静态挂载会自动托管，后端不用改。
- 开发时 Vite dev server 把 `/api` 代理到 `http://127.0.0.1:8000`；凭据联调优先用构建监听模式，让新旧页面统一从后端同一来源访问。
- 用 `openapi-typescript` 从 `/openapi.json` 生成 API 类型，保证前后端契约一致。

### 页面

- 访问地址：`/app/editor/?run=<run_id>`。
- token 从浏览器存储 `noworrycv-run-history` 中按 run_id 读取，并兼容 `profile` 参数对应的 `noworrycv-candidate-archives` 档案凭据及当前会话凭据。
- 入口：旧结果页增加“在编辑器中打开”按钮。

### 功能与接口

| 功能 | 接口 |
| --- | --- |
| 加载结果，结构化编辑各模块和条目 | `GET /tailor-runs/{id}/status` |
| 保存，并重新计算匹配分 | `PUT /tailor-runs/{id}/draft`，然后 `POST /tailor-runs/{id}/score` |
| 撤销 / 重做 | 前端维护 past / present / future 三个栈，不需要后端 |
| 历史版本列表和恢复 | `GET /tailor-runs/{id}/draft-versions`、`POST /tailor-runs/{id}/draft-versions/{vid}/restore` |
| 与原文的差异对比 | `POST /tailor-runs/{id}/draft-diff` |
| 单条局部重写 | `POST /tailor-runs/{id}/rewrite-part` |

### 验收

用 Playwright 走一遍：生成 → 打开编辑器 → 改一条 → 撤销 → 重做 → 保存 → 分数刷新 → 恢复旧版本。

---

## 4. Docker

### `Dockerfile`（多阶段构建）

1. `node:22` 阶段：安装前端依赖并构建编辑器。
2. `python:3.12-slim` 阶段：
   - 安装项目依赖和 `fonts-noto-cjk`，保证 PDF 导出中文正常；
   - 拷入编辑器构建产物；
   - 以非 root 用户运行 `uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`。

### `docker-compose.yml`

- `db`：`postgres:16`，挂数据卷，用 `pg_isready` 做健康检查。
- `app`：
  - `depends_on` 等待 `db` 健康；
  - 设置 `DATABASE_URL=postgresql://...@db:5432/noworrycv`；
  - 从 `.env` 读取模型密钥；
  - `.dist` 挂成数据卷（另外 6 个 SQLite 库仍在其中）；
  - 映射端口 8000，插件不用改配置。

### `.dockerignore`

排除 `.venv`、`.dist`、`.env`、`node_modules`、`__pycache__`。

### 验收

`docker compose up -d` 后完整跑一遍生成；执行 `docker compose restart app`，确认任务和草稿都还在。

---

## 执行顺序

1. 新建 git 分支，确认 Docker Desktop 可用，安装依赖。
2. PostgreSQL（任务队列 + 草稿库）。
3. SSE。
4. React 编辑器。
5. Docker。
6. 全量测试回归，更新 README（启动方式、`DATABASE_URL`、编辑器入口、Docker 部署）。

## 完成后同步修改简历

- 按实际 OpenAPI 统计更新接口数量；执行前基线为 81 个接口操作、67 条路径。
- 存储写为“任务与草稿版本持久化至 PostgreSQL（本地开发默认 SQLite）”。

## 执行记录

- 2026-10-19：保存升级前工作快照到 `.dist/stack-upgrade-baseline/`，开发分支 `feat/minimal-stack-upgrade`。
- 数据迁移采用独立命令，保留任务、凭据哈希、过期时间、检查点和草稿版本；先在副本验证，不自动切换现有数据。
- PostgreSQL 首版只允许单应用进程，线程任务队列保留；不提供多副本部署承诺。
- 编辑器的嵌套构建资源需包含在 Python 包内。

### 本轮进度

- PostgreSQL：实现完成，使用本机独立 PostgreSQL 16 实例验收；支持单进程会话锁、增量 JSONB 写入、幂等领取、事务检查点、取消重试、重启恢复及只读源文件迁移。
- SSE：实现完成，鉴权、状态变化、心跳、终态与浏览器轮询降级已验收。
- React 编辑器：构建完成，TypeScript 固定 5.9.3 以兼容 openapi-typescript；新旧页面共享凭据，编辑、撤销重做、段落单独修改保存、评分、差异、局部重写和版本恢复已验收。
- 兼容修正：按用户确认补齐仅带 run 参数时恢复指定任务，兼容 run+profile 的插件入口。
- Docker：多阶段镜像、非 root 运行、数据库健康检查、中文字体和两个持久卷配置已完成，`docker compose config --quiet` 通过；按用户要求暂缓实际镜像构建与容器运行验收。
- 回归：322 项后端测试通过（含 6 项真实 PostgreSQL 集成），24 项前端及插件 JavaScript 检查通过；编辑器构建及 Python wheel 嵌套资源检查通过。
- 模型验证使用 stub，不产生真实模型请求；Docker 验收完成前 P1-007 保持进行中。
- 补充浏览器验收：仅档案凭据访问、run+profile 返回、仅 run 恢复指定任务、SSE 请求失败后轮询、真实应用进程重启恢复、正文聚焦时撤销重做及保存后刷新；320 / 390 / 768 / 1024 / 1440 像素无横向溢出。
- 按用户确认修正正文显示同步：撤销、重做和版本恢复通过快照修订号刷新正文框，避免局部编辑状态残留。
- 测试环境未提供 TEST_DATABASE_URL 时为 316 项通过、6 项 PostgreSQL 测试跳过；提供隔离数据库时全部 322 项通过。
