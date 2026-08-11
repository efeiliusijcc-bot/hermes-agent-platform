# Hermes Agent Platform

Hermes Agent Platform 是面向企业内网的离线 Agent 基础平台。平台以 Hermes Agent Runtime 为执行核心，通过外部 OpenAI Compatible 模型服务完成推理，并组合 Agent、Skill、MCP、Knowledge 与 Memory 构建可配置、可隔离的 AI 工作单元。

## 当前阶段

当前仓库处于 **Phase 1：基础服务**。PostgreSQL/pgvector、Redis 与 MinIO 通过独立 Compose 项目运行，仅加入内部网络，不发布宿主机端口。

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
