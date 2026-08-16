# Phase 5 Multi-Agent Orchestration 实现说明

本阶段依据 `Hermes_Multi_Agent_Architecture_Design.md`，在现有 Agent 隔离、Task Queue、Worker Pool、Artifact、Memory 和执行历史之上增加多 Agent 编排能力。

## 1. 运行边界

- Hermes Control Plane 管理 Agent、Team、Workflow、权限和生命周期。
- `hermes-orchestrator` 独立进程推进 DAG、等待子任务、处理人工审批并触发 Manager 汇总。
- `agent-worker` 并发执行已就绪任务，并通过 Redis Stream 回传结果事件。
- Runtime Adapter 隔离 Hermes 与 Pi。选择 `pi` 时只调用独立 Pi Runtime HTTP 服务，平台不直接链接 Pi 代码。
- Skill、MCP、Knowledge 仍按 Agent 绑定加载，不因 Team 共享而扩大权限。

## 2. 数据模型

Alembic `0011_multi_agent_orchestration` 增加：

- `agents.agent_type / parent_agent_id / runtime_type`
- `agent_teams / team_members`
- `workflows / workflow_runs`
- `agent_tasks.parent_task_id / workflow_run_id / node_key / depends_on`
- `agent_sessions.runtime_type / runtime_session_id`
- `agent_skill.version`

任务状态扩展为：

```text
pending -> running -> succeeded
    |          |
    |          +-> retrying -> running
    +-> waiting_child
    +-> human_review
    +-> failed / cancelled
```

数据库状态使用小写，API 和前端保持同一枚举，避免大小写双轨。

## 3. API

### Agent Team

- `POST /api/agent-teams`
- `GET /api/agent-teams`
- `GET/PATCH/DELETE /api/agent-teams/{team_id}`
- `PUT/DELETE /api/agent-teams/{team_id}/members/{agent_id}`
- `POST /api/agent-teams/{team_id}/runs`

Team owner 必须是已启用的 Manager Agent。Owner 自动成为优先级 100 的 Team Member，且不能直接移除。

### Workflow

- `POST/GET /api/workflows`
- `GET/PATCH/DELETE /api/workflows/{workflow_id}`
- `POST /api/workflows/{workflow_id}/runs`
- `GET /api/workflow-runs`
- `GET /api/workflow-runs/{run_id}`
- `DELETE /api/workflow-runs/{run_id}`
- `GET /api/workflow-runs/{run_id}/tasks`

Workflow 在入库前检查节点唯一性、依赖存在性和环路。Agent Node 必须指向 Team Member。Tool、Skill 和 Condition Node 由指定 Agent（未指定时由 Manager）执行，因此仍受该 Agent 的 Skill/MCP 权限边界约束。

### Human Approval 和 Agent Message

- `POST /api/tasks/{task_id}/approval`
- `POST/GET /api/agent-messages`

Agent Message 使用 `AGENT_MESSAGE_STREAM_KEY` 指定的 Redis Stream。管理 API 只允许同一 Team 内 Agent 互发消息。

## 4. 调度语义

直接运行 Team 时，所有 Worker 并行执行；全部成功后，Manager Task 获得带 Agent/节点来源的结果并生成最终汇总。

运行 Workflow 时，仅入队依赖已满足的节点。人工审批节点进入 `human_review`，审批通过后才释放下游节点。任一子任务耗尽重试后失败，Run 和 Manager Root Task 同步失败。`hermes-orchestrator` 重启后会从数据库重新扫描活动 Run，不依赖进程内状态。

## 5. Runtime 配置

```dotenv
ORCHESTRATOR_POLL_SECONDS=1
AGENT_MESSAGE_STREAM_KEY=hermes:agent-messages:v1
AGENT_MESSAGE_MAX_LENGTH=10000
PI_RUNTIME_ENDPOINT=http://pi-runtime:8765
PI_RUNTIME_API_KEY=
PI_RUNTIME_TIMEOUT_SECONDS=180
```

Pi Runtime 是可选外部执行服务。未部署 Pi 时，应保持 Agent 的 `runtime_type=hermes`。平台健康检查不强制探测未启用的 Pi。

## 6. 非 Docker 验证

```bash
PYTHONPATH=backend backend/.venv/bin/pytest -q backend/tests
cd frontend
npm test -- --run
npm run build
```

Compose 容器启动、迁移和 10 Agent 并发验收必须在 116 测试节点执行，本机不运行 Docker。

116 隔离验收命令：

```bash
docker compose -p hermes-agent-multi-verify \
  -f docker-compose.yml \
  -f docker-compose.phase4.verify.yml \
  -f docker-compose.multi-agent.verify.yml \
  up -d --build --wait
API_URL=http://127.0.0.1:38588 ./tests/multi_agent_orchestration.sh
```

该脚本验证 10 个 Worker 并发、11 个独立 Session、Manager 汇总、DAG 依赖释放、Human Approval 及 Redis Agent Message 结果回传。
