# Hermes Agent Platform 当前状态审计

审计基线：`0014_runtime_integration_layer`。

## 已有能力

- Agent、Skill、MCP、Knowledge、Runtime、Agent Version、Execution、Trace、Artifact 和多 Agent 编排已投入使用。
- Hermes、Pi、DeepSeek Runtime 通过统一 Adapter 运行。
- PostgreSQL、Redis、MinIO、Worker Pool 和 Model Gateway 已部署。
- `agent_mcp` 只支持只读 filesystem/database；历史 Agent Version 使用 `format_version=1`。

## 升级前缺口

- 没有通用 Capability、Connector、Operation、Resource Scope、Invocation Audit 和 Console BFF。
- Skill 没有独立不可变版本和抽象 Capability Requirement。
- 信源召回是 Agent 执行中的特殊分支。
- Hermes 的旧 MCP 提示曾包含执行 Token。
- 控制台没有登录和用户级 RBAC，管理操作缺少统一安全边界。

## 兼容边界

- `Agent.capability_profile` 继续表示 Workspace、旧工具要求和 Artifact 类型。
- `format_version=1`、`agent_mcp`、旧 API 和历史 Execution 均保留。
- 新 Agent Draft 仅通过 Console BFF 路径升级为 `format_version=2`。
- 数据库变更只增加表、列和索引，不删除历史数据。
