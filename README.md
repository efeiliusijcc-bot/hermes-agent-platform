# Hermes Agent Platform

Hermes Agent Platform 是面向企业内网的离线 Agent 基础平台。平台以 Hermes Agent Runtime 为执行核心，通过外部 OpenAI Compatible 模型服务完成推理，并组合 Agent、Skill、MCP、Knowledge 与 Memory 构建可配置、可隔离的 AI 工作单元。

## 当前阶段

当前仓库处于 **Phase 7：Knowledge 能力**。独立 `knowledge-service` 负责 Markdown、文本、PDF、Word `.docx` 和 Excel `.xlsx` 的解析、切片、离线 Embedding、MinIO 原文存储与 pgvector 向量检索。Agent 只检索自身绑定且启用的 Knowledge Source，召回片段以不可信资料注入上下文，执行日志只保留文档/分片 ID 和分数。

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

## 设计依据

项目唯一架构依据是 [docs/hermes_agent_offline_platform_detailed_design.md](docs/hermes_agent_offline_platform_detailed_design.md)。如实现与文档发生架构冲突，应停止开发并先确认设计变更。

Phase 6 的权限边界、Memory 命名空间和 116 验收步骤见 [docs/phase6-agent-isolation.md](docs/phase6-agent-isolation.md)。

Phase 7 的 Knowledge 数据模型、解析/Embedding 边界和验收步骤见 [docs/phase7-knowledge-service.md](docs/phase7-knowledge-service.md)。

## 校验

本地只执行不依赖 Docker 的校验：

```bash
./scripts/validate-phase0.sh
```

Compose 校验和容器测试只允许在 116 测试节点执行：

```bash
HAP_VALIDATE_COMPOSE=1 ./scripts/validate-phase0.sh
```

Phase 1 基础设施测试仅在 116 节点执行：

```bash
set -a
. ./.env
set +a
./tests/phase1_infrastructure.sh
```
