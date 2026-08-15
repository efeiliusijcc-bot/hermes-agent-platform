# Hermes Agent Platform

The platform now includes the Phase 10 Agent Schema / public API contract, the Phase 3 Agent isolation / concurrency runtime, Phase 3.1 Schema and storage abstractions, and the Phase 4 production Agent runtime. See `docs/phase2-registry-publication.md`, `docs/phase3-agent-isolation-concurrency.md`, `docs/phase3.1-schema-storage.md`, and `docs/phase4-production-agent-runtime.md`.

Hermes Agent Platform 是面向企业内网的离线 Agent 基础平台。平台以 Hermes Agent Runtime 为执行核心，通过外部 OpenAI Compatible 模型服务完成推理，并组合 Agent、Skill、MCP、Knowledge 与 Memory 构建可配置、可隔离的 AI 工作单元。

## 当前阶段

当前仓库已完成 **Phase 10：Agent Schema 与 API Gateway**、Phase 3 隔离并发、Phase 3.1 Schema/Storage，以及 Phase 4 生产 Agent Runtime。除 `knowledge-analyst` 多源分析和离线恢复能力外，平台支持版本化 Input/Output Schema、API Version 固定绑定、Prompt Template、Model Adapter、API Client/Key、生命周期、发布/回滚、审计/指标、健康门禁、Sync JSON、原生 SSE Stream、异步队列、MinIO Artifact 和 Redis/PostgreSQL/pgvector Memory。

管理控制台 MVP 已按现有 FastAPI 契约实现，包含运行总览、Agent 创建/详情/删除、Skill/MCP 展示、能力绑定、Playground、Sync/SSE 模式选择、实时 Trace 和执行日志查看。SSE 直接转发 Hermes Runtime 原生增量事件，不使用伪流式切分。

Hermes API Server 的原生 terminal、文件、浏览器、内置 Skill、委派等工具集已关闭，仅启用 `mcp-gateway`。这保证 Agent 不能绕过平台绑定直接使用 Hermes 本地工具。

`model-stub` 只属于自动化测试 profile，用于验证 OpenAI 协议、Hermes 调度和日志闭环，不是模型实现，也不能作为真实模型验收证据。生产部署不得启用该 profile。

Skill 路径必须是 `skills/` 下的相对目录名。注册接口会在写入数据库前验证目录边界、必需文件、UTF-8/YAML 内容及配置 ID，避免目录穿越和无效 Skill 延迟到执行阶段才暴露。

第一阶段 MCP 统一经 `MCP_GATEWAY_ENDPOINT` 接入，只允许只读 filesystem/database 类型。文件路径限制在 `data/mcp-files/`，数据库查询同时使用语句类型检查、PostgreSQL 只读事务、超时和返回行数限制。

`POST /api/agents/{id}/run` 接受可选 `session_id`，默认值为 `default`。会话上下文只加载同一 `agent_id + session_id` 最近的消息；删除 Agent 时会先清理该 Agent 的 Redis 记忆，避免 ID 重建后读到旧上下文。

## 第一阶段核心闭环

```text
创建 Agent
  -> 绑定 Skill
  -> 绑定 MCP
  -> Hermes 执行
  -> 调用模型
  -> 返回结果
  -> 记录执行日志
```

## 目录

```text
backend/    后端控制服务与运行时适配
frontend/   管理控制台
services/   基础服务及网关配置
skills/     Agent Skill 存储
configs/    系统配置
docker/     离线部署文件
docs/       架构与开发文档
tests/      自动化测试
scripts/    开发、校验和部署脚本
```

## 配置原则

- 所有环境配置从环境变量读取。
- `.env.example` 仅提供变量模板，真实密钥不得提交到 Git。
- 116 测试节点统一使用 Compose 项目名 `hermes-agent-platform`。
- 116 上现有 `hermes`、`hermes-api` 及其网络、卷、端口不属于本项目，禁止修改。
- 300B 模型不部署在 116，通过 `MODEL_ENDPOINT` 调用外部 OpenAI Compatible API。
- 管理控制台默认绑定 `127.0.0.1:18089`，经 Nginx 同源代理调用 `agent-api`，不会把内部容器地址暴露给浏览器。116 节点的 `18080` 已被其他项目使用，因此本项目不占用该端口。

## 设计依据

项目唯一架构依据是 [docs/hermes_agent_offline_platform_detailed_design.md](docs/hermes_agent_offline_platform_detailed_design.md)。如实现与文档发生架构冲突，应停止开发并先确认设计变更。

Phase 6 的权限边界、Memory 命名空间和 116 验收步骤见 [docs/phase6-agent-isolation.md](docs/phase6-agent-isolation.md)。

Phase 7 的 Knowledge 数据模型、解析/Embedding 边界和验收步骤见 [docs/phase7-knowledge-service.md](docs/phase7-knowledge-service.md)。

Phase 8 的 Knowledge Analyst Demo 配置、部署、调用和验收步骤见 [docs/phase8-knowledge-agent-demo.md](docs/phase8-knowledge-agent-demo.md)。

Phase 9 的镜像导出、配置/数据迁移、新节点恢复和 116 隔离验收步骤见 [docs/phase9-offline-deployment.md](docs/phase9-offline-deployment.md)。

Phase 10 的 Agent Schema、Prompt Builder、Model Adapter、公开 API 与 SSE 契约见 [docs/phase2-registry-publication.md](docs/phase2-registry-publication.md)。

Phase 3 的 Agent/Session/Workspace/Artifact 隔离、Task Queue、Worker Pool、模型并发保护和 116 独立验收步骤见 [docs/phase3-agent-isolation-concurrency.md](docs/phase3-agent-isolation-concurrency.md)。

Phase 3.1 的 Schema/API 版本生命周期、Artifact Storage Provider、Memory Provider 和 116 独立验收证据见 [docs/phase3.1-schema-storage.md](docs/phase3.1-schema-storage.md)。

Phase 4 的生产生命周期、Client/Key 鉴权、限流、审计、指标、健康门禁、版本回滚及 116 独立验收证据见 [docs/phase4-production-agent-runtime.md](docs/phase4-production-agent-runtime.md)。控制面管理员认证尚未定义，因此管理接口只允许放在可信内网或由外层可信网关保护，不能直接暴露公网。

## 校验

本地只执行不依赖 Docker 的校验：

```bash
./scripts/validate-phase0.sh
```

Compose 校验和容器测试只允许在 116 测试节点执行：

```bash
HAP_VALIDATE_COMPOSE=1 ./scripts/validate-phase0.sh
```

前端本地类型检查、生产构建和单元测试不使用 Docker：

```bash
cd frontend
npm ci
npm test
npm run build
```

在 116 节点启动管理控制台：

```bash
docker compose -p hermes-agent-platform up -d --build --wait frontend
curl -fsS http://127.0.0.1:18089/frontend-health
curl -fsS http://127.0.0.1:18089/health
```

Phase 1 基础设施测试仅在 116 节点执行：

```bash
set -a
. ./.env
set +a
./tests/phase1_infrastructure.sh
```
