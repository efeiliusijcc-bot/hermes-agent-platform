# ADR 0001：通用 Capability 平台

状态：Accepted

## 决策

- Skill 只声明抽象 Capability Requirement，不保存真实 Endpoint 或凭据。
- Connector Revision 保存连接配置并通过 `credential_ref` 引用 Fernet 加密凭据。
- Agent Version v2 冻结 Capability Binding、Scope Revision 和 `resolution_digest`。
- Runtime 只接收 Tool Alias、业务 Schema 和短期 Execution Token；模型不可看到 Token。
- 第一阶段扩展现有 `mcp-gateway`，同时保留旧 `/mcp`。
- 前端只使用 Console BFF 判断 Preflight 和发布条件。

## 安全边界

- 控制台暂不提供登录。启用 `PLATFORM_MANAGEMENT_API_KEY_ENABLED` 后，控制面写操作必须携带 `X-Platform-Management-Key`。
- 管理密钥只保存在浏览器内存，刷新后清除。
- Credential 明文不得进入 Snapshot、Prompt、Tool Arguments、Trace、Artifact 或普通日志。
- Gateway 固定解析 Binding，Runtime 不能指定 Endpoint、Credential、Implementation 或 Resource Scope。

## 兼容与回滚

- v1 Snapshot 继续走 Legacy Tool Adapter。
- v2 Snapshot 走 Resolver 和 Capability Gateway。
- 官方 Hermes Gateway 支持每次运行的 MCP Header 前，v1 Hermes 保留短期 `mcp2` 参数兼容；v2 `cap1` Token 仍只由平台内部 Dispatcher 使用。
- 回滚只关闭 Feature Flag 并恢复上一版镜像；增量表保留。
