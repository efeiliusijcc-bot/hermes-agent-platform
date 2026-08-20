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

- 控制台暂不提供登录，面向可信内网直接开放控制面读写操作；页面不保存或发送平台解锁凭据。
- 控制台端口不得暴露到不可信网络，后续引入统一身份系统时再实现用户级认证与 RBAC。
- Credential 明文不得进入 Snapshot、Prompt、Tool Arguments、Trace、Artifact 或普通日志。
- Gateway 固定解析 Binding，Runtime 不能指定 Endpoint、Credential、Implementation 或 Resource Scope。

## 兼容与回滚

- v1 Snapshot 继续走 Legacy Tool Adapter。
- v2 Snapshot 走 Resolver 和 Capability Gateway。
- 官方 Hermes Gateway 支持每次运行的 MCP Header 前，v1 Hermes 保留短期 `mcp2` 参数兼容；v2 `cap1` Token 仍只由平台内部 Dispatcher 使用。
- 回滚只关闭 Feature Flag 并恢复上一版镜像；增量表保留。
