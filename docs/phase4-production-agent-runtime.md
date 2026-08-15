# Phase 4 生产级 Agent Runtime

Phase 4 在现有 Agent、Schema、Session、Workspace、Artifact、Memory 与 Worker 能力之上，增加生产调用所需的生命周期、发布门禁、Client 鉴权、审计、指标、健康检查及版本回滚。本阶段的 116 验证只能使用独立 Compose 项目，不会更新正式 Hermes 服务。

## 控制面安全边界

Phase 4 文档定义的是业务系统调用公共 Agent API 时的 Client/Key 鉴权，没有定义管理员登录、SSO 或 RBAC。当前仓库的 Agent、发布/回滚、API Client/Key、Skill、MCP 等 `/api/*` 管理接口因此只能部署在可信内网，并由外层网关做管理员认证和访问控制；在补齐并验证控制面身份方案前，禁止把管理控制台或这些管理接口直接暴露公网。公共 `/api/public/agents/*` 与 `/api/{api_version}/agents/*` 仍按下文的 Client Key 契约鉴权。

## 生命周期与调用边界

Agent 生命周期为：

```text
draft -> testing -> published -> suspended -> archived
```

- `draft`：允许编辑，不允许执行。
- `testing`：允许平台内部测试接口，不允许公共 API 调用。
- `published`：通过发布健康门禁后允许公共 API 调用。
- `suspended`：暂停内部和公共调用，可恢复到 `published`。
- `archived`：终态，拒绝执行和配置变更。

不允许跳过测试直接从 `draft` 发布，也不允许从 `archived` 回退。旧客户端提交的 `active`、`disabled` 分别规范化为 `testing`、`suspended`，但 API 响应和数据库只使用新生命周期值。

## API Client、Key 与限流

业务系统先创建 API Client，再生成 Key，并将 Client 以 `invoke` 权限绑定到 Agent。公共调用继续支持：

```text
POST /api/public/agents/{agent_id}/run
POST /api/public/agents/{agent_id}/stream
POST /api/{api_version}/agents/{agent_id}/run
POST /api/{api_version}/agents/{agent_id}/stream
X-API-Key: <secret>
```

Key 明文只在创建响应中返回一次。数据库只保存 SHA-256 和非敏感前缀；列表接口绝不返回明文。鉴权同时检查 Key、Client、过期时间、Agent 绑定、`invoke` 权限和 Agent 发布状态。撤销 Key、暂停 Client、解除绑定或暂停 Agent 后立即拒绝调用。

每个 Client 有每分钟限额。超过限额返回 HTTP 429，限流拒绝也进入审计，但不执行模型。

旧的 `POST /api/agents/{agent_id}/publication/api-key` 入口仅作为迁移期控制面兼容入口保留。它签发的 Key 也会创建到标准 `api_clients` / `api_keys` / `agent_api_clients` 模型中，公共调用不再直接比对 `agent_publications.api_key_hash`。因此迁移 Key 与新 Client Key 使用完全相同的 Client 状态、Key 撤销/过期、Agent 绑定、限流和审计归属检查；Publication 中的 Hash/Prefix 只用于旧控制面数据同步，不能绕过标准鉴权。

## 审计与敏感数据边界

公共同步、SSE、鉴权拒绝、Schema 拒绝、运行失败均写审计。审计只保存：

- request ID、Client/Key/Agent ID；
- 成功、失败或拒绝状态；
- latency、token usage、MCP 调用次数；
- 受控错误码和时间。

审计表和接口不保存请求 input、Prompt、模型输出、API Key 明文或其他业务敏感正文。普通 execution/session 仍可能按既有运行语义保存内部输入输出，因此生产访问必须继续受平台管理权限控制。

## 指标语义

Agent 指标聚合调用次数、成功/失败次数、成功率、平均耗时、Token 消耗和 MCP 调用次数。同步和 SSE 都只在一次调用的终态计数一次。

`token_usage = null` 表示聚合窗口中至少一次调用没有底层 Runtime 明确提供 Token 数据，不能解释为零消耗，也不能用已知调用的局部总数冒充完整总数。只有实际观测到 usage 时才累加底层值；失败和拒绝仍计入调用与失败指标，便于计算真实错误率。116 隔离验收会同时证明成功审计中存在明确的正 Token 值，以及成功/拒绝混合后的聚合 Token 保持 `null`。

## 健康门禁

Agent 健康检查至少覆盖 Model、绑定 Skill 和绑定 MCP。发布前必须完成健康检查；Model 不可用或必要依赖异常时拒绝发布。`healthy` 可发布，`degraded` 的处理必须由后端明确配置，不能静默忽略失败检查。

## 版本、发布和回滚

Agent Version 保存不可变快照：Prompt、Model/Adapter/配置、Prompt Template、Skill 绑定、MCP 绑定、Schema 版本、公共 API Version 到 Schema 的绑定及响应模式。发布将快照指定的公共契约与目标版本一起生效，并把 Agent 置为 `published`。

回滚不是只改版本号：必须在一次数据库事务中恢复快照里的配置、Skill/MCP 绑定、Schema 内容以及公共 API Version 到 Schema Version 的实际绑定。116 验收会在回滚后立即重新做健康检查并精确核对绑定，公共调用只能看到完整恢复后的契约。

## 116 独立验证

独立验证固定使用：

- Compose 项目：`hermes-agent-phase4-verify`
- API：`127.0.0.1:38488`
- 前端：`127.0.0.1:38489`
- 独立镜像、named volumes 和网络

准备一个只含测试值的环境文件，例如 `/opt/hermes-agent-phase4-verify/phase4.verify.env`。不得复制或读取正式 `.env`。在独立源码目录执行：

```sh
docker compose \
  --env-file /opt/hermes-agent-phase4-verify/phase4.verify.env \
  -p hermes-agent-phase4-verify \
  -f docker-compose.yml \
  -f docker-compose.phase4.verify.yml \
  build

docker compose \
  --env-file /opt/hermes-agent-phase4-verify/phase4.verify.env \
  -p hermes-agent-phase4-verify \
  -f docker-compose.yml \
  -f docker-compose.phase4.verify.yml \
  up -d

API_URL=http://127.0.0.1:38488 \
HERMES_COMPOSE_PROJECT_NAME=hermes-agent-phase4-verify \
HERMES_COMPOSE_FILES="-f /opt/hermes-agent-phase4-verify/docker-compose.yml -f /opt/hermes-agent-phase4-verify/docker-compose.phase4.verify.yml" \
POSTGRES_USER=phase4 \
POSTGRES_DB=phase4 \
tests/phase4_production_runtime.sh
```

验收通过后保留必要日志、迁移 head、表结构和测试输出证据，再清理本次独立资源：

```sh
docker compose \
  --env-file /opt/hermes-agent-phase4-verify/phase4.verify.env \
  -p hermes-agent-phase4-verify \
  -f docker-compose.yml \
  -f docker-compose.phase4.verify.yml \
  down --volumes --remove-orphans
```

清理前后必须核对正式容器 ID 未变化。本流程不授权正式部署、正式数据库迁移、正式镜像替换、公网端口变更，也不授权删除任何非 `hermes-agent-phase4-verify` 资源。

## 2026-08-13 验收记录

Phase 4 已在 116 节点使用上述独立命名空间从空 PostgreSQL/Redis/MinIO/Hermes/Workspace/Artifact 卷完成验收，Alembic 为 `0008_production_runtime (head)`。`tests/phase4_production_runtime.sh` 全量通过，覆盖：

- Draft → Testing → Published → Suspended → Archived 生命周期与发布健康门禁；
- 标准 Client/Key/Binding、迁移 Key 标准化、暂停/撤销/解绑/限流拒绝；
- Sync/SSE、输入输出 Schema、非敏感审计、真实 Token 与未知聚合 Token 语义；
- Prompt/Model/Skill/MCP/Schema/API Version 回滚及 Publication 门禁恢复；
- Key 仅存 Hash/Prefix、调用计数与审计/指标单事务。

验收过程中实际捕获并修复了 PostgreSQL `FOR UPDATE` 与 eager `LEFT OUTER JOIN` 的锁目标冲突，修复后再次从空卷完整通过。结束后已删除 `hermes-agent-phase4-verify` 的容器、卷、网络、四个验证镜像和 `/opt/hermes-agent-phase4-verify`；正式 `hermes-agent-platform-*` 容器 ID 前后未变化。该记录只证明隔离验证，不代表已提交 Git、更新正式服务、重打离线包或完成控制面公网安全。
