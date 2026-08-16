# Pi Runtime Adapter 接入说明

## 范围

平台只实现 Pi Runtime Adapter 和治理控制面，不复制、不修改 Pi Harness 源码。Pi Runtime 必须作为独立服务部署，并向 Agent API 提供 HTTP 接口。

本阶段新增：

- `agent_runtimes` Runtime 注册表和健康状态。
- Agent 的 `runtime_type`、`runtime_config.runtime_id`。
- Skill 的 `runtime_support` 兼容声明。
- Execution 的 `runtime_type`、`runtime_id`、`runtime_version`。
- Pi Session、同步执行、SSE、停止和健康检查适配。
- Workspace、Memory Namespace、Skill、MCP Gateway 上下文注入。
- Pi Trace 到平台 `runtime/skill/mcp/model/artifact` 节点的转换。

## Pi Runtime HTTP 契约

Pi 服务至少提供：

```text
GET  /health
POST /sessions
POST /sessions/{session_id}/execute
POST /sessions/{session_id}/stream
POST /runs/{run_id}/stop
```

`POST /sessions` 会收到平台生成的执行上下文：

```json
{
  "agent_id": "knowledge-agent",
  "execution_id": "...",
  "context": {
    "agent_id": "knowledge-agent",
    "session_id": "...",
    "workspace": "/data/workspaces/...",
    "memory_namespace": "agent:knowledge-agent:session:report-1",
    "tools": ["filesystem", "database"],
    "skills": ["write-hb"],
    "metadata": {
      "mcp_gateway": "http://mcp-gateway:8090/mcp",
      "mcp_access_token": "execution-scoped token",
      "memory_mode": "platform-managed",
      "artifact_mode": "platform-managed"
    }
  }
}
```

Pi 不应绕过 MCP Gateway 直接访问数据库。Memory 由平台在执行前读取、执行后写入；最终文本由平台保存到 Workspace 和 Artifact Storage。

同步返回至少包含文本输出：

```json
{
  "run_id": "pi-run-1",
  "status": "completed",
  "output": "result",
  "usage": {"total_tokens": 100},
  "trace": [
    {"type": "model_call", "status": "succeeded", "duration_ms": 120}
  ]
}
```

SSE 支持平台原生事件名，也兼容常见的 `token/delta/done/error/tool_call/tool_result` 名称。流必须产生完成事件，不能无状态结束。

## Runtime 注册

密钥只通过 `PI_RUNTIME_API_KEY` 环境变量提供。Runtime 和 Agent 的 JSON 配置禁止保存 `api_key`、`password`、`secret`、`token` 等凭据。

```bash
curl -X POST http://127.0.0.1:8080/api/runtimes \
  -H 'Content-Type: application/json' \
  --data '{
    "name":"内网 Pi Runtime",
    "type":"pi",
    "version":"0.20.0",
    "endpoint":"http://pi-runtime:8765",
    "config":{"health_path":"/health","timeout_seconds":180},
    "status":"unknown"
  }'
```

注册后调用 `POST /api/runtimes/{runtime_id}/health`，确认状态为 `online`，再在 Agent 的 `runtime_config.runtime_id` 中绑定该 ID。

## Skill 兼容

Pi Agent 只能绑定显式声明支持 Pi 的 Skill：

```yaml
runtime_support:
  - hermes
  - pi
```

未声明时默认仅支持 `hermes`。平台在绑定、切换 Runtime 和执行前三处进行阻断，避免把不兼容 Skill 发送给 Pi。

## 真实验收

准备好独立 Pi Runtime 后执行：

```bash
API_URL=http://127.0.0.1:8080 \
PI_RUNTIME_TEST_ENDPOINT=http://pi-runtime:8765 \
PI_RUNTIME_TEST_VERSION=0.20.0 \
PI_RUNTIME_TEST_MODEL=内网模型名 \
sh tests/pi_runtime_adapter.sh
```

脚本验证 Runtime 健康、Agent 绑定、同步执行、SSE、Session、Memory Namespace、Artifact、Execution 和 Trace。没有真实 Pi 服务时只能完成代码与契约测试，不能声称 Pi 端到端已通过。
