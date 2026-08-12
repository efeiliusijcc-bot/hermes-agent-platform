# Enterprise Agent Control Center MVP

## 目标

管理控制台严格调用当前 FastAPI 已实现的接口，完成以下闭环：

```text
创建 Agent
  -> 绑定 Skill / MCP / Knowledge
  -> 提交任务
  -> Hermes 执行
  -> 展示结果与 ExecutionLog
```

## 技术栈

- Vue 3 Composition API
- TypeScript
- Vite
- Pinia
- Vue Router
- Naive UI
- Axios
- Nginx 静态托管与同源反向代理

## API 映射

| 前端能力 | 后端接口 |
|---|---|
| Agent 列表、创建、详情、删除 | `/api/agents`、`/api/agents/{id}` |
| Agent 执行与历史 | `/api/agents/{id}/run`、`/api/agents/{id}/runs` |
| Skill 列表和绑定 | `/api/skills`、`/api/agents/{id}/skills/{skill_id}` |
| MCP 列表和绑定 | `/api/mcp-servers`、`/api/agents/{id}/mcp-servers/{mcp_id}` |
| Knowledge 绑定 | `/api/knowledge-sources`、`/api/agents/{id}/knowledge-sources/{source_id}` |
| 平台状态 | `/health` |

## 明确边界

- 后端没有 `PATCH /api/agents/{id}`，MVP 不提供基础配置编辑。
- 创建 Agent 时不能直接提交 `skills` 或 `mcps`。前端创建成功后调用独立绑定接口。
- Agent 创建与能力绑定不是同一事务。部分绑定失败时保留 Agent，并显示准确失败项。
- `model_config` 当前是保存的 Agent 元数据。HermesClient 仍使用平台级 `HERMES_MODEL`。
- Agent 执行是同步 JSON 接口。前端等待完成后查询 ExecutionLog，不模拟 SSE 或 WebSocket 流式事件。
- 执行过程只展示后端记录的 `skills_loaded`、`mcp_calls`、`knowledge_hits` 和 `memory_scope`。

## 本地开发

本地开发仅运行 Node，不运行本机 Docker：

```bash
cd frontend
npm ci
npm run dev
```

Vite 默认把 `/api` 和 `/health` 代理到 `http://127.0.0.1:18088`。需要更换时设置：

```bash
VITE_DEV_API_PROXY=http://目标地址:端口 npm run dev
```

生产构建：

```bash
npm test
npm run build
```

## 116 节点部署

Compose 中的 `frontend` 是本项目独立构建的容器，不修改 116 上已有的 `hermes` 或 `hermes-api` 容器。

默认端口：

```text
127.0.0.1:18089 -> frontend:8080
127.0.0.1:18088 -> agent-api:8000
```

启动与检查：

```bash
docker compose -p hermes-agent-platform up -d --build --wait frontend
curl -fsS http://127.0.0.1:18089/frontend-health
curl -fsS http://127.0.0.1:18089/health
curl -fsS http://127.0.0.1:18089/api/agents
```

如果需要从其他机器访问，应通过已有的安全入口或 SSH 隧道暴露，不建议直接把控制台绑定到公网地址。当前 MVP 尚无用户认证和 RBAC。
