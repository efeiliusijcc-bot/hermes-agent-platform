# Phase 6 Agent 隔离设计与验收

## 1. 隔离边界

### Skill

Agent API 只读取当前 Agent 在 `agent_skill` 中的绑定，并只把这些 Skill 的内容注入本次执行上下文。Hermes API Server 的原生 `skills` 工具集不启用，因此 Agent 无法浏览或加载 Hermes 自带 Skill 绕过平台绑定。

### MCP

每次执行由 Agent API 签发短期 HMAC 执行句柄。句柄只携带压缩后的 `execution_id` 和签名；当前 Agent 的 capability 快照在调用 Hermes 前写入对应执行日志，不包含数据库密码或平台密钥。短句柄降低模型原样传参时发生字符错误的概率。

MCP Gateway 在工具主体执行前验证签名，然后按 `execution_id` 从 PostgreSQL 读取 Agent 身份、执行状态、开始时间和 capability 快照。只有仍为 `running` 且未超过 TTL 的执行可以调用工具。有效句柄请求未绑定工具时返回拒绝，并向对应 `execution_logs.details.mcp_calls` 原子追加 `status=denied` 的审计摘要。无效签名不可信，直接拒绝且不写入任何 Agent 的日志。

Hermes 的 `platform_toolsets.api_server` 只允许 `mcp-gateway`。terminal、文件写入、浏览器、内置 Skill、委派、代码执行等原生工具均不进入 Agent 工具面，防止绕过 MCP Gateway。

### Memory

第一阶段使用 Phase 1 已部署的 Redis 保存短期会话上下文。键空间固定为：

```text
hermes:agent-memory:v1:{agent_id}:{session_id}
```

`session_id` 只允许字母、数字、点、下划线和连字符。运行时只读取当前 `agent_id + session_id` 的最近消息；相同 `session_id` 在不同 Agent 下仍是不同键。消息数量、单条长度和 TTL 均由环境变量限制。

历史消息以“不可信会话数据”JSON 注入，不得改变 System Prompt、Skill 或 MCP 权限。Hermes 自带 Memory 被关闭，避免出现第二套未按平台 Agent 命名空间隔离的记忆。

删除 Agent 时，控制平面先精确清理该 Agent 的 Redis 命名空间；Redis 不可用时拒绝删除，避免相同 Agent ID 重建后继承旧上下文。

## 2. 审计字段

成功执行的 `execution_logs.details` 至少包含：

```json
{
  "skills_loaded": [],
  "mcp_loaded": [],
  "mcp_calls": [],
  "memory_scope": {
    "namespace": "agent_session",
    "agent_id": "agent-id",
    "session_id": "session-id",
    "history_messages_loaded": 0
  }
}
```

日志和接口响应不得包含 MCP 能力令牌、Redis 密码、数据库密码或模型密钥。

## 3. 116 部署边界

- 目录固定为 `/opt/hermes-agent-platform`。
- Compose 项目名固定为 `hermes-agent-platform`。
- 只构建 `hermes-agent-platform/agent-api:phase6` 和 `hermes-agent-platform/mcp-gateway:phase6`。
- 只更新本项目 Compose 服务。
- 不在本机运行 Docker。
- 不查看、停止、重建或删除 116 上非本项目容器、网络、卷和端口。

## 4. 自动验收

在 116 项目目录加载 `.env` 后执行：

```sh
./tests/phase6_agent_isolation.sh
```

脚本确定性验证：

1. Agent A 仅绑定 filesystem，Agent B 仅绑定 database。
2. Agent A 与 Agent B 的 Skill 列表不同，执行日志只记录自身绑定。
3. Hermes API Server 只启用 `mcp-gateway`。
4. Agent A 的有效 filesystem 令牌调用 database 时被网关拒绝。
5. 拒绝事件写入 Agent A 的执行日志，且没有令牌泄漏。
6. Agent A 文件调用与 Agent B 数据库调用分别成功。
7. 两个 Agent 使用相同 `session_id` 时 Redis 键和模型上下文仍隔离。
8. 删除 Agent 只清理该 Agent 的 Memory。
