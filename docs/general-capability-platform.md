# 通用 Capability 平台部署与使用

## Feature Flag

```text
CAPABILITY_PLATFORM_ENABLED=false
CAPABILITY_GATEWAY_ENABLED=false
CONSOLE_BFF_ENABLED=false
LEGACY_MCP_BINDING_READ_ENABLED=true
LEGACY_VECTOR_TOOL_ENABLED=true
PLATFORM_MANAGEMENT_API_KEY_ENABLED=true
```

`PLATFORM_MANAGEMENT_API_KEY`、`MODEL_REGISTRY_ENCRYPTION_KEY` 和 Connector 真实密钥不得写入仓库或离线包，应在目标节点 `.env` 或 Docker Secret 中单独配置。

## 升级顺序

1. 备份 PostgreSQL、`.env`、镜像列表和容器 ID。
2. 执行 `alembic upgrade head`，确认 Head 为 `0016_capability_binding_and_invocation`。
3. 在所有新执行 Flag 关闭时更新 `agent-api`、`agent-worker`、`mcp-gateway`、`pi-runtime` 和 `frontend`。
4. 使用管理接口 `POST /api/capability-platform/migrations/import-legacy` 导入旧 MCP 和信源召回配置。
5. 打开 `CAPABILITY_PLATFORM_ENABLED`，完成 Registry、BFF 和 Preflight 验收。
6. 仅给测试 Agent 配置 v2 Binding，再打开 `CAPABILITY_GATEWAY_ENABLED`。
7. Hermes、Pi、DeepSeek 验收通过后打开 `CONSOLE_BFF_ENABLED`。
8. 新旧召回对比通过后关闭 `LEGACY_VECTOR_TOOL_ENABLED`。

## 管理模式

- 页面刷新后默认为只读模式。
- 点击控制台右上角“管理员解锁”，输入平台管理密钥。
- 密钥只存在于当前页面内存，不保存到 localStorage。
- Credential API 永远只返回 `masked_label`、状态和轮换时间。

## Capability 调用

Runtime 只能提交：

```json
{
  "execution_id": "exe_xxx",
  "tool_name": "source_search",
  "arguments": {"query": "示例", "top_k": 10}
}
```

Execution Token 位于内部请求 Header。Gateway 负责 Schema、Parameter Policy、Resource Scope、Quota、Credential、超时、重试、输出校验和 Invocation Audit。

内部 Resolver 同样只接受 Execution Token：

```http
POST /internal/capabilities/resolve
POST /internal/capabilities/invoke
```

## Legacy MCP 兼容边界

- v1 Snapshot 仍使用原 `mcp2` 执行参数协议，保证已发布 Agent 无需重新发布。
- Pi 在模型可见 Schema 中删除 `access_token`，再由 Runtime Dispatcher 注入。
- 官方 Hermes Gateway 当前只有静态 MCP Header，v1 仍使用历史短期 `mcp2` 参数；该兼容 Token 不是 Connector Credential，也不是 v2 `cap1` Execution Token。
- v2 Capability Tool Schema 始终不包含 Token、Endpoint、Connector ID、Credential 或 Scope。

## 回滚

1. 关闭 `CAPABILITY_GATEWAY_ENABLED`。
2. 保持 `LEGACY_MCP_BINDING_READ_ENABLED=true` 和 `LEGACY_VECTOR_TOOL_ENABLED=true`。
3. 关闭 `CONSOLE_BFF_ENABLED` 并恢复上一版前端镜像。
4. 恢复上一版 `agent-api`、Worker 和 Gateway 镜像。
5. 不删除 `0015/0016` 新表，不改写已发布 v1/v2 Snapshot。
