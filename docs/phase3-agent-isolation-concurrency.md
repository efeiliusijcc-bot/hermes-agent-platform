# Phase 3 Agent Isolation and Concurrency

本阶段在已有 Agent Schema、Skill、MCP、Knowledge、Memory 和同步/SSE 执行契约上，增加逻辑隔离的 Session、Workspace、Artifact、异步 Task Queue、Worker Pool 和模型并发保护。Agent 仍不是一 Agent 一容器；隔离边界由数据库外键、Redis 命名空间、受控文件路径、能力快照和 Worker 执行上下文共同保证。

## 数据模型

Alembic 迁移 `0006_agent_isolation` 新增：

- `agent_sessions`：内部 UUID、Agent、调用方 Session 键、生命周期、输入输出和 Workspace 相对路径。
- `agent_tasks`：Agent、Session、优先级、状态、尝试次数、Worker、错误和时间戳。
- `artifacts`：Agent、Session、文件名、受控相对路径、Content-Type、大小和 SHA-256。
- `execution_logs.session_id`：把原有执行日志关联到内部 Session。
- `agent_mcp.permission`：绑定级只读权限；执行时固化到 capability 快照。

一次同步、SSE 或异步执行都创建独立的内部 Session UUID。调用方提供的 `session_id` 仅作为同一 Agent 内的 Memory 会话键；即使两个 Agent 使用相同键，数据库 Session、Redis Memory、Workspace 和 Artifact 也不会复用。

## Workspace 与 Artifact

Workspace 固定为：

```text
/data/workspaces/{agent_id}/sessions/{internal_session_uuid}/
├── input/
├── output/
└── temp/
```

`WorkspaceManager` 拒绝非法 Agent ID、非法文件名、绝对路径、符号链接逃逸和 `..` 目录穿越。API 和 Worker 共享 `/data/workspaces`；Hermes Runtime 不挂载该目录，只使用自己的 `/opt/data` 状态目录。

Worker 把最终文本写入 `output/result.txt`，再登记 Artifact 的相对路径、大小和 SHA-256。下载前重新解析边界并计算 SHA-256：文件不存在返回 410，摘要不匹配返回 409。

## Task Queue 与 Worker Pool

异步入口把数据库事务和 Redis 入队分开处理：

```text
POST task
  -> 创建 queued Session 和 pending Task
  -> Redis 按 priority 入队
  -> Worker 原子认领并锁定 Task 行
  -> 执行 Agent
  -> 保存 Session / ExecutionLog / Artifact
  -> succeeded、retrying、failed 或 cancelled
```

优先级范围是 0 到 9，9 最高。Worker 支持进程内并发、失败重试、延迟重入队和启动时恢复 stale running Task。数据库认领只锁 `agent_tasks` 行；Session 关系使用 `selectinload`，避免 PostgreSQL 对 outer join 执行 `FOR UPDATE` 的限制。

关键环境变量：

```text
WORKER_CONCURRENCY=4
TASK_QUEUE_KEY=hermes:agent-tasks:v1
TASK_QUEUE_POLL_SECONDS=1
TASK_MAX_ATTEMPTS=3
TASK_RETRY_DELAY_SECONDS=1
TASK_STALE_SECONDS=600
WORKSPACE_ROOT=/data/workspaces
```

## 模型访问保护

所有 Hermes 模型请求仍经 `model-gateway`。网关增加：

- `MODEL_MAX_CONCURRENCY` 并发信号量。
- `MODEL_QUEUE_TIMEOUT_SECONDS` 等待容量超时。
- `MODEL_MAX_RETRIES` 和 `MODEL_RETRY_DELAY_SECONDS`，仅对非流式 429/502/503/504 请求重试。
- `/health` 返回 `active`、`peak` 和 `max_concurrency`，用于验收和监控。

流式请求在上游响应关闭后才释放容量；非流式请求在成功或异常的 `finally` 中释放。队列等待超时返回 503，上游超时返回 504，其他网络错误返回 502。

## Skill 与 MCP 隔离

- Skill Loader 只读取当前 Agent 的绑定项。
- MCP Gateway 只接受短时、签名的执行令牌；令牌只包含执行 UUID 的压缩表示，不携带完整 capability 清单。
- capability 和 `permission=read_only` 从当前 Agent 绑定关系写入执行快照。
- Gateway 每次工具调用用执行记录重新确认 Agent、MCP 类型、只读权限和运行中状态。
- 工具令牌不写入执行输出、错误、审计详情或普通日志。

## Runtime 无状态边界

Hermes Runtime 不持有 Agent 业务状态，也不挂载全体 Agent Workspace。当前 Hermes v2026.8.3 配置使用 `_config_version=33`、`terminal.cwd=/opt/data`、`terminal.home_mode=auto`。Agent 配置、Session 和任务在 PostgreSQL，Memory 和队列在 Redis，业务文件在 API/Worker 管理的 Workspace。

这里的“无状态”不表示 Runtime 容器内完全没有 Hermes 自身运行文件；`/opt/data` 仍保存 Runtime 配置、缓存和运行日志。边界是 Runtime 不拥有 Agent Workspace，也不能直接读取其他 Agent 产物。

## API

- `POST /api/agents/{id}/tasks`：提交异步任务，返回 202 和 Task。
- `GET /api/tasks`、`GET /api/tasks/{id}`：查询队列和任务状态。
- `DELETE /api/tasks/{id}`：取消尚未被 Worker 认领的任务。
- `GET /api/sessions`、`GET /api/sessions/{id}`：查询 Session 生命周期。
- `GET /api/artifacts`、`GET /api/artifacts/{id}`：查询 Artifact 元数据。
- `GET /api/artifacts/{id}/download`：边界和摘要校验后下载。
- `GET /api/agents/{id}/workspace`：返回该 Agent 的 Session、Artifact 和字节数汇总。

原有 `POST /api/agents/{id}/run` 同步 JSON 和 SSE 契约保持兼容。

## 前端

- Playground 增加“异步队列”执行模式和优先级。
- 执行中心展示 Task、排队/运行/失败统计、Session 和 Artifact 下载。
- Agent 详情展示 Workspace 根、Session、运行任务和 Artifact 统计。
- Dashboard 使用真实 Task API 展示队列状态，不伪造 Worker 指标。

## 本地验证

本机不运行 Docker，只执行代码测试和构建：

```bash
backend/.venv/bin/pytest -q backend/tests
cd frontend
npm test
npm run build
cd ..
git diff --check
```

## 116 独立验收

验收必须使用独立项目，不得停止、重建或复用正式 `hermes-agent-platform` 的容器、网络和数据目录：

```text
目录      /opt/hermes-agent-phase3-verify
项目名    hermes-agent-phase3-verify
API       127.0.0.1:38188
Frontend  127.0.0.1:38189
```

测试 profile 使用 `model-stub`，不会调用互联网或真实外部模型。生产部署禁止启用该 profile。

```bash
cd /opt/hermes-agent-phase3-verify
set -a
. ./.env
set +a
export AGENT_API_PORT=38188
export HERMES_COMPOSE_PROJECT_NAME=hermes-agent-phase3-verify

docker compose \
  -p hermes-agent-phase3-verify \
  -f docker-compose.yml \
  -f docker-compose.verify.yml \
  --profile test up -d --wait

./tests/phase3_isolation_concurrency.sh
./tests/phase6_agent_isolation.sh
./tests/phase10_phase2_platform.sh
```

Phase 3 验收创建两个 Agent，并发提交相同 Memory Session 键，要求：

- 内部 Session UUID 不同。
- Workspace 和 Artifact 路径不同。
- Artifact A/B 内容不串线，下载 SHA-256 校验成功。
- 两个任务均为 `succeeded`。
- Runtime 实际加载 `/opt/data`，不存在 `/workspace`。
- Model Gateway 最终 `active=0`，且 `1 <= peak <= max_concurrency=2`。

2026-08-13 在 116 节点的独立验收中，Phase 3、Phase 6 和 Phase 10 脚本均通过；模型并发指标为 `active=0`、`peak=2`、`max_concurrency=2`。这是隔离验收，不是对正式平台的部署。

验收完成后只清理 `hermes-agent-phase3-verify` 项目的容器、专用网络、v3 验证镜像和验证目录。不得删除共享基础镜像，也不得使用模糊项目名。清理前后必须对比正式九个核心容器的 ID 和 healthy 状态。
