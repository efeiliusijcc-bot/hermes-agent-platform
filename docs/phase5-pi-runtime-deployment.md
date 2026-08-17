# Phase 5.0 Pi Runtime 部署与集成

## 实现边界

平台部署独立 `pi-runtime` 服务，运行官方 MIT 许可的
[`@earendil-works/pi-agent-core`](https://www.npmjs.com/package/@earendil-works/pi-agent-core)
`0.84.2`。平台没有复制或修改 Pi 源码；锁定后的 npm 依赖由
`services/pi-runtime/package-lock.json` 固化并进入 Docker 镜像。

```text
Agent API / Worker
  -> PiRuntimeAdapter
  -> pi-runtime (official Pi Agent Core)
     -> model-gateway -> internal OpenAI-compatible model
     -> mcp-gateway   -> authorized read-only tools
```

`pi-runtime` 只加入独立的 `pi-runtime-internal` 内部网络，不映射宿主机
端口，不挂载 Workspace、数据库或 Artifact 目录。PostgreSQL、Redis、MinIO 和
Hermes Runtime 都不加入该网络，因此 Pi 容器无法直接解析或连接这些服务。
Workspace、Memory、Artifact、Execution 和 Schema 仍由平台控制面管理。

## HTTP 契约

- `GET /health`
- `POST /sessions`
- `POST /sessions/{session_id}/execute`
- `POST /sessions/{session_id}/stream`
- `POST /stop/{execution_id}`

同时保留设计文档中的无 Session 别名 `POST /execute`、`POST /stream`，以及旧
Adapter 的兼容停止地址 `POST /runs/{run_id}/stop`。

除 `/health` 外全部接口要求 `Authorization: Bearer ${PI_RUNTIME_API_KEY}`。

## Context、Skill 和 MCP

Agent API 在执行前完成以下工作：

1. 校验 Agent、Input Schema 和 Skill 的 `runtime_support`。
2. 加载 `SKILL.md`、workflow 与 references，渲染为受控 Prompt。
3. 创建平台 Workspace、Memory namespace 和 Execution。
4. 签发仅对当前 Execution 有效的 MCP access token。
5. 将 Context 交给 Pi Adapter。

Pi Runtime 只把已授权的 capability 映射为 Pi Tool：

- `filesystem` -> `filesystem_read`
- `database` -> `database_query`

工具调用必须经过 `mcp-gateway`。每次调用的 access token 只放在平台交给
Pi Runtime 的内部 Context 中，不拼入模型 Prompt；Pi 在模型完成 Tool 选择后才
注入该 token。token 不会出现在模型可见的 Tool Schema、Trace、Artifact 或
日志中。未绑定、已过期或
Execution 已结束的 token 会被 MCP Gateway 拒绝。

## 模型访问

Pi 使用 `@earendil-works/pi-ai` 的 OpenAI-compatible provider，但 endpoint 固定为
内部 `http://model-gateway:8080/v1`。Pi Runtime 不保存真实模型地址和上游模型密钥；
它只持有内部 `MODEL_GATEWAY_API_KEY`。

## 运行控制

- 默认最多并发 4 个 Pi Run，其余请求进入有界等待队列。
- Session 默认 30 分钟未使用后过期，最多保留 1000 个。
- 平台 Execution ID 同时作为 Pi Run ID，便于跨服务停止和追踪。
- `POST /api/executions/{execution_id}/stop` 会调用 Pi `/stop/{execution_id}`，并将
  Execution、Session、Task 和运行中的 Trace Step 统一标记为 `cancelled`。
- SSE 客户端断开时 Pi Agent 会收到 abort，避免孤儿推理继续占用模型并发。

## 关键配置

```dotenv
PI_RUNTIME_ENDPOINT=http://pi-runtime:8765
PI_RUNTIME_API_KEY=<独立随机密钥，至少 32 字符>
PI_RUNTIME_VERSION=0.84.2
PI_RUNTIME_TIMEOUT_SECONDS=180
PI_RUNTIME_MAX_CONCURRENCY=4
PI_RUNTIME_QUEUE_TIMEOUT_SECONDS=60
PI_RUNTIME_SESSION_TTL_SECONDS=1800
PI_RUNTIME_MAX_SESSIONS=1000
PI_RUNTIME_CONTEXT_WINDOW=131072
PI_RUNTIME_MAX_OUTPUT_TOKENS=8192
RUNTIME_AUTO_REGISTER=true
```

`scripts/ensure-runtime-secrets.sh` 会补齐缺失的 Pi Runtime 密钥和 MCP 签名密钥，
不会输出密钥内容。真实部署的 `.env` 必须保持 `0600`，不得提交 Git。

## 部署与离线交付

只在 116 或目标 Linux 构建：

```bash
./scripts/ensure-runtime-secrets.sh .env
docker compose build pi-runtime agent-api frontend
docker compose up -d --wait pi-runtime agent-api agent-worker hermes-orchestrator frontend
```

内网恢复不执行 npm 或镜像拉取。先在联网交付节点完成镜像构建，再运行
`scripts/create-offline-bundle.sh`；Compose 的 `config --images` 会把
`hermes-agent-platform/pi-runtime:phase5` 自动写入 `images.tar`。

## 验收

最低验收必须同时包含：

1. Runtime Registry 中 Hermes 与 Pi 均为 `online`。
2. Pi Hello Agent 同步执行成功，Execution/Session/Artifact/Trace 均记录 `pi`。
3. Pi File Agent 真实调用 `filesystem_read`，MCP 审计可查。
4. Pi Knowledge Agent 加载 `write-hb`、召回证据并生成结构化 Artifact。
5. Pi SSE 返回真实 token 增量和 `end=success`。
6. 运行中 stop 后 Execution、Session、Task、Trace 统一为 `cancelled`。
7. `pi-runtime` 无宿主机端口、无数据库网络直连、无公网出口、日志无内部密钥。

116 节点执行：

```bash
set -a
. ./.env
set +a
PI_RUNTIME_TEST_MODEL="$MODEL_NAME" ./tests/pi_runtime_deployment.sh
```

Knowledge Agent 验收会检查上游召回的 `diagnostics`。如果仍出现
`embedding retrieval unavailable`，只能记为降级召回；报告必须在
`information_gaps` 披露，没有与主题直接相关的证据时必须返回 `blocked`。

验收脚本入口：`tests/pi_runtime_deployment.sh`。
