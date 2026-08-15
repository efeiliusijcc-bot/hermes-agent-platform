# Phase 3.1 Schema Version 与 Storage Abstraction

## 交付范围

本阶段在 Phase 3 的 Session、Workspace、Artifact、Task Queue 和 Worker 基础上增加：

- `agent_schema_versions`：每个 Agent 的 Input/Output Schema 历史版本。
- `agent_api_versions`：API Version 与 Schema Version 的固定绑定。
- Artifact Storage Provider：`local`、`minio`、`nas` 统一 `save/get/delete/exists` 接口。
- Memory Provider：`redis`、`postgres`、PostgreSQL `pgvector` 统一 CRUD。
- Memory Namespace：`agent_id/session_id/memory_type`，所有读写必须带完整命名空间。

数据库迁移为 `0007_schema_storage`。升级时已有 Agent 会回填 `v1` Schema 和 `v1` API：已发布 Agent 继续保持 published；未发布 Agent 保持 draft。旧 Artifact 被标记为 `workspace` Provider，仍可下载。

## Schema 生命周期

固定生命周期：

```text
draft -> testing -> published -> deprecated -> disabled
```

规则：

- `draft`、`testing` 可修改或删除。
- `published` 后 Schema 和 API 绑定不可修改、不可删除。
- `published`、`deprecated` 均允许历史 API 调用。
- `disabled` 拒绝调用。
- API 发布前，其绑定的 Schema 必须已 published。

兼容接口 `PUT /api/agents/{agent_id}/schema` 只允许修改 draft/testing 的 `v1`。已发布后必须新建版本。

## 管理 API

Schema Version：

- `POST /api/agents/{agent_id}/schema-versions`
- `GET /api/agents/{agent_id}/schema-versions`
- `GET /api/agents/{agent_id}/schema-versions/{version}`
- `PUT /api/agents/{agent_id}/schema-versions/{version}`
- `PUT /api/agents/{agent_id}/schema-versions/{version}/status`
- `DELETE /api/agents/{agent_id}/schema-versions/{version}`

API Version：

- `POST /api/agents/{agent_id}/api-versions`
- `GET /api/agents/{agent_id}/api-versions`
- `GET /api/agents/{agent_id}/api-versions/{api_version}`
- `PUT /api/agents/{agent_id}/api-versions/{api_version}/binding`
- `PUT /api/agents/{agent_id}/api-versions/{api_version}/status`
- `DELETE /api/agents/{agent_id}/api-versions/{api_version}`

管理控制台的“API 管理 → 版本管理”已对接上述接口，可创建和编辑未发布 Schema、创建或改绑未发布 API Version、按固定生命周期推进状态，并显示每个 API Version 的实际调用入口。后端仍是生命周期和不可变规则的最终校验方。

公开调用：

- `POST /api/{api_version}/agents/{agent_id}/run`
- `POST /api/{api_version}/agents/{agent_id}/stream`
- 兼容入口 `POST /api/public/agents/{agent_id}/run|stream` 固定解析为 `v1`。

## Artifact Storage

默认：

```dotenv
ARTIFACT_STORAGE_PROVIDER=minio
ARTIFACT_MINIO_BUCKET=artifacts
ARTIFACT_MAX_BYTES=104857600
```

执行完成后先在 Workspace 写入 `output/result.txt`，再通过 Provider 持久化。数据库只登记 `storage_type`、`storage_path`、Content-Type、大小和 SHA-256。下载时从登记的 Provider 读取并重新计算 SHA-256；摘要不一致返回 409，不可用返回 410。

Local/NAS 适用于共享挂载或单 Worker；多 Worker 默认使用 MinIO。切换 NAS 时需把同一 NAS 路径挂载为所有 API/Worker 容器的 `/data/artifacts`。

## Memory Storage

默认：

```dotenv
MEMORY_PROVIDER=redis
MEMORY_TYPE=short-term
```

可切换 `MEMORY_PROVIDER=postgres`，数据存入 `agent_memories`；或切换 `MEMORY_PROVIDER=vector`，同时把确定性 384 维 embedding 存入 `agent_memory_vectors`，供后续相似度检索扩展。Redis Provider 首次读取时兼容迁移旧 `hermes:agent-memory:v1:{agent_id}:{session_id}` 消息列表。

通用 CRUD：

- `GET /api/agents/{agent_id}/memory/{session_id}/{memory_type}/{key}`
- `PUT /api/agents/{agent_id}/memory/{session_id}/{memory_type}/{key}`，Body 为 `{"value": ...}`
- `DELETE /api/agents/{agent_id}/memory/{session_id}/{memory_type}/{key}`

Agent ID、Session ID、Memory Type 和 Key 均经过安全格式验证，接口中的 Agent ID同时用于数据库存在性校验，不能借由请求体覆盖。

## 升级验证

```bash
docker compose run --rm agent-api alembic upgrade head
docker compose exec -T agent-api alembic current
curl -fsS http://127.0.0.1:18088/health
```

验收时至少验证：

1. `v1` published 后创建 `v2`，两个版本用各自 Schema 校验。
2. `v1` deprecated 后仍可调用，disabled 后拒绝调用。
3. Worker 生成 Artifact，API 容器可下载且 `X-Artifact-SHA256` 与内容一致。
4. 同名 Session 在不同 Agent 下 Memory 不可互读。
5. 切换 Redis/Postgres Provider 后 CRUD 与对话消息语义一致。

## 116 独立验证

Phase 3.1 使用独立 Compose 项目 `hermes-agent-phase31-verify` 验证，不复用或修改正式 Hermes 容器。验证内容包括：

- Alembic 单一 head 为 `0007_schema_storage`，四张新增表实际存在。
- v1/v2 按各自 Schema 成功调用；v1 deprecated 后仍可调用，disabled 后返回不可用。
- 两个 Worker 并发执行两个 Agent，产物写入 MinIO；API 容器可下载，内容与登记 SHA-256 一致。
- Redis、PostgreSQL、pgvector 三种 Memory Provider 均完成 CRUD 和 Agent/Session Namespace 隔离验证；向量维度为 384。
- 管理控制台生产镜像健康，真实浏览器可打开版本管理弹窗并读取 v1 Schema 状态。

自动化脚本：

```bash
API_URL=http://127.0.0.1:38288 \
API_KEY_FILE="$(mktemp)" RESPONSE_FILE="$(mktemp)" \
sh tests/phase31_schema_storage.sh

HERMES_COMPOSE_PROJECT_NAME=hermes-agent-phase31-verify \
HERMES_COMPOSE_FILES="-f /opt/hermes-agent-phase31-verify/docker-compose.yml -f /opt/hermes-agent-phase31-verify/docker-compose.phase31.verify.yml" \
AGENT_API_PORT=38288 sh tests/phase3_isolation_concurrency.sh
```
