# Hermes Agent Platform v2.5.0 离线部署手册

> 交付日期：2026-08-12
> 适用架构：Linux x86_64
> 默认管理控制台端口：18089
> 当前公开的脱敏明文包已在 116 节点的独立 Compose 项目中完成离线恢复验收；数据库迁移版本为 `0004_agent_response_mode`。此前源验收包已完成 Phase 2.5 Sync JSON / SSE Stream 测试，目标内网仍需使用实际模型服务复验业务推理。

> 版本边界：本手册记录的现有 `v2.5.0` 离线包仍是迁移 `0004_agent_response_mode`，不包含当前源码新增的 Agent Schema/API Gateway v2（迁移 `0005_agent_gateway_contract`）。在重新生成离线包及 SHA-256 之前，不得把当前源码验证结果写成旧离线包已具备的能力。

## 1. 交付物与校验值

| 项目 | 值 |
|---|---|
| 脱敏离线包 | `hermes-agent-platform-v2.5.0-offline-x86_64.tar.gz` |
| 离线包 SHA-256 | `e9d1b0620eb9ad3abb0b65397638bbbb6b53a5302242d7e96f11adc43f82a9ef` |
| 离线包大小 | `1,353,679,685 bytes`（约 1.3 GiB） |
| 数据库迁移版本 | `0004_agent_response_mode` |

**重要：** 公网离线包不含源环境的明文密码、API Key 或签名密钥。根目录 `.env` 是待配置模板；部署前必须执行 `./scripts/configure-offline-env.sh`，在内网生成新的内部密钥并写入内网模型配置。

## 2. 部署架构与离线边界

平台恢复后启动 9 个长期服务：Frontend、Agent API、Model Gateway、Hermes Runtime、MCP Gateway、Knowledge Service、PostgreSQL/pgvector、Redis 和 MinIO。

- 容器镜像、平台源码、配置、PostgreSQL/Redis/MinIO 数据、Hermes 工作目录和 MCP 文件都在离线包内；恢复时不会从 Docker Hub、GitHub、PyPI 或 npm 下载内容。
- 默认只将管理控制台发布到 `18089`，Agent API `18088` 仅绑定 `127.0.0.1`。
- **模型推理服务不包在本离线包内。** 目标节点必须能访问一个 OpenAI Compatible 模型服务，该服务可以是同一内网中的离线模型节点。
- 若要做物理断网部署，请先将离线包、同名 `.sha256` 和本手册转移到目标网络；部署过程本身不需要公网。

## 3. 目标节点要求

- Linux x86_64。
- Docker Engine 和带 `docker compose` 子命令的 Compose v2。
- `tar`、`gzip`、`sha256sum` 和 `curl`。
- 建议至少预留 15–20 GiB 可用磁盘空间；实际占用会随数据和日志增长，请按生产数据量扩容。
- 当前用户能够运行 Docker，且目标端口未被占用。
- 目标节点可访问配置的 OpenAI Compatible 模型地址。

部署前检查：

```bash
uname -m
docker version
docker compose version
df -hP /opt
ss -lnt | grep -E ':(18088|18089)\\b' || true
```

`uname -m` 应返回 `x86_64`。如端口已被占用，参见第 10 节。

## 4. 下载并校验离线包

```bash
mkdir -p ~/hermes-offline-install
cd ~/hermes-offline-install

BASE_URL='http://116.204.135.83:28086'
PACKAGE='hermes-agent-platform-v2.5.0-offline-x86_64.tar.gz'

curl -fLO "$BASE_URL/$PACKAGE"
curl -fLO "$BASE_URL/$PACKAGE.sha256"
sha256sum -c "$PACKAGE.sha256"
```

成功时应显示：

```text
hermes-agent-platform-v2.5.0-offline-x86_64.tar.gz: OK
```

支持断点续传：

```bash
curl -fL -C - -O "$BASE_URL/$PACKAGE"
```

## 5. 解压到空目录

> 恢复脚本会拒绝覆盖非空 `data/` 目录。若 `/opt/hermes-agent-platform` 已存在，请先判断它是否属于现有部署；不要直接删除或覆盖。

```bash
sudo install -d -m 0755 /opt/hermes-agent-platform
sudo tar -xzf ~/hermes-offline-install/hermes-agent-platform-v2.5.0-offline-x86_64.tar.gz \
  -C /opt/hermes-agent-platform \
  --strip-components=1
sudo chown -R "$(id -u):$(id -g)" /opt/hermes-agent-platform
cd /opt/hermes-agent-platform
```

确认关键文件存在：

```bash
test -f .env
test -f images.tar
test -f SHA256SUMS
test -x scripts/restore-offline-bundle.sh
```

## 6. 配置 `.env`

离线包中的 `.env` 是脱敏占位模板。先运行下列脚本；它会先从包内 `images.tar` 执行 `docker load`，再以 `--network none` 容器生成新密钥并询问内网模型配置，不会联网。

```bash
cd /opt/hermes-agent-platform
./scripts/configure-offline-env.sh
```

脚本完成后再审核 `.env`。恢复脚本会拒绝任何未替换的 `REPLACE_BEFORE_DEPLOY` 占位符。

重点变量：

| 变量 | 建议 |
|---|---|
| `FRONTEND_BIND_HOST` | 本机使用保持 `127.0.0.1`；需从可信局域网访问时设为 `0.0.0.0` |
| `FRONTEND_PORT` | 默认 `18089` |
| `AGENT_API_BIND_HOST` | 建议保持 `127.0.0.1`，不直接对外暴露 |
| `AGENT_API_PORT` | 默认 `18088` |
| `MODEL_ENDPOINT` | OpenAI Compatible 接口根地址，通常以 `/v1` 结尾 |
| `MODEL_API_KEY` | 模型服务 API Key；如内网服务仍要求 Key，填写实际值 |
| `MODEL_NAME` | 模型服务实际接受的模型名 |
| `POSTGRES_PASSWORD` | 更换为强随机值 |
| `REDIS_PASSWORD` | 更换为强随机值 |
| `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` | 更换为新环境凭据 |
| `HERMES_API_KEY` / `MODEL_GATEWAY_API_KEY` | 使用新的强随机值 |
| `MCP_GATEWAY_SIGNING_KEY` | 至少 32 个随机字符，不与其他 Key 复用 |

**容器访问模型的注意事项：** `MODEL_ENDPOINT=http://127.0.0.1:.../v1` 在容器内通常指向容器自身，而不是 Docker 主机。请使用容器可达的内网 IP、DNS 名或同一 Compose 网络中的服务名。

## 7. 执行离线恢复

```bash
cd /opt/hermes-agent-platform

OFFLINE_PROJECT_NAME=hermes-agent-platform \
OFFLINE_AGENT_API_PORT=18088 \
OFFLINE_FRONTEND_PORT=18089 \
  ./scripts/restore-offline-bundle.sh
```

脚本会按顺序执行：

1. 校验包内除可配置 `.env` 外的不可变文件；`.env` 单独校验占位符已全部替换且权限为 `0600`。
2. 从 `images.tar` 执行 `docker load`，并确认所有镜像存在。
3. 准备持久化目录，恢复 Redis RDB 及带 TTL 的逻辑键快照。
4. 启动 PostgreSQL、Redis、MinIO，恢复数据库和对象。
5. 启动剩余服务，并检查 Agent API 与前端健康端点。

离线恢复期间不会执行 `docker build` 或从网络拉取镜像。

## 8. 验收清单

### 8.1 服务状态

```bash
cd /opt/hermes-agent-platform
docker compose -p hermes-agent-platform ps
```

应看到 9 个长期服务处于 `Up` / `healthy`。`hermes-init` 是一次性初始化服务，正常情况下它会完成后退出，不计入 9 个长期服务。

### 8.2 HTTP 健康检查

```bash
curl -fsS http://127.0.0.1:18089/frontend-health
curl -fsS http://127.0.0.1:18089/health
```

然后用浏览器打开：

```text
http://目标节点IP:18089
```

### 8.3 数据库迁移版本

```bash
cd /opt/hermes-agent-platform
docker compose -p hermes-agent-platform exec -T postgres \
  psql -U "$(sed -n 's/^POSTGRES_USER=//p' .env)" \
       -d "$(sed -n 's/^POSTGRES_DB=//p' .env)" \
       -Atc 'select version_num from alembic_version;'
```

期望输出：

```text
0004_agent_response_mode
```

### 8.4 业务验收

- 登录控制台，确认 Agent、Skill、MCP、知识库和 API 管理页面可打开。
- 在 Playground 中分别选择 `Sync JSON` 和 `SSE Stream`，各执行一次。
- `SSE Stream` 应实时显示 `start` / `trace` / `tool` / `token` / `end` 等事件；不应把完整结果伪切分为流。
- 对已发布 Agent，外部调用方可用 `?response_mode=sync|stream` 覆盖 Agent 默认值。

## 9. 日常运维

```bash
cd /opt/hermes-agent-platform

# 状态
docker compose -p hermes-agent-platform ps

# 启动或更新已加载服务（不拉取镜像）
docker compose -p hermes-agent-platform up -d --wait --pull never

# 停止（保留容器和数据）
docker compose -p hermes-agent-platform stop

# 重启
docker compose -p hermes-agent-platform restart

# 最近 200 行日志
docker compose -p hermes-agent-platform logs --tail=200

# 持续查看 Agent API 日志
docker compose -p hermes-agent-platform logs -f agent-api
```

不要对生产目录随意执行 `docker compose down -v`；`-v` 可能删除命名卷。本项目的主要数据映射在 `/opt/hermes-agent-platform/data/`，但仍应在删除任何容器、卷或目录前核对实际挂载。

## 10. 常见故障

### 10.1 `Restore target data directory is not empty`

恢复目标不是空环境。先确认目录所属及是否需要保留；不要为了继续恢复而盲目删除。新建一个空部署目录，或在完成备份并获得删除授权后再处理。

### 10.2 端口占用

```bash
ss -lntp | grep -E ':(18088|18089)\\b'
```

可在 `.env` 和恢复命令中使用其他未占用端口；两处必须保持一致。

### 10.3 模型服务不可达

先在主机上检查模型地址，再从 `model-gateway` 容器所在网络检查。重点排查容器内的 `127.0.0.1`、DNS、路由、TLS 证书和 API Key。

```bash
docker compose -p hermes-agent-platform logs --tail=200 model-gateway hermes-runtime
```

### 10.4 外部无法访问控制台

确认 `FRONTEND_BIND_HOST=0.0.0.0`，并确认主机防火墙、云安全组只对可信网段放行 `18089/tcp`。不建议直接向公网无限制开放。

### 10.5 磁盘空间不足

```bash
df -hP /opt
docker system df
du -sh /opt/hermes-agent-platform/* 2>/dev/null | sort -h
```

先识别资源所属和挂载关系，再制定清理范围。不要在共享节点上盲目执行 `docker system prune -a --volumes`。

## 11. 安全要求

- 当前管理控制台未提供完整的登录/RBAC 边界，`18089` 只应向可信管理网络开放，或放在启用身份认证和 TLS 的反向代理之后。
- 保持 `AGENT_API_BIND_HOST=127.0.0.1`，不对外直接暴露 `18088`。
- 部署后应更换所有密钥，对 `.env` 执行 `chmod 600`，并限制 `/opt/hermes-agent-platform` 的 SSH/文件权限。
- 下载完成后，将离线包移入受控制品库。公网下载端口不应作为长期制品库。
- 内网生成的 `.env` 和明文 API Key 不得回传到下载页、工单、Git 仓库或日志。

## 附录 A：SSE Stream 调用示例

在控制台的 API 管理页生成 API Key，将 Agent 发布为 `published`，然后执行：

```bash
curl -N -X POST \
  'http://目标节点IP:18089/api/public/agents/AGENT_ID/run?response_mode=stream' \
  -H 'X-API-Key: hap_...' \
  -H 'Content-Type: application/json' \
  --data '{"topic":"分析企业知识库"}'
```

平台稳定事件名为 `start`、`trace`、`tool`、`token`、`end`、`error` 和 `keepalive`。流已经返回 HTTP 200 后发生的运行或输出 Schema 错误，会作为 `error` 事件返回。

## 附录 B：重要文件

- `docker-compose.yml`：平台服务编排。
- `.env`：实际运行配置，含敏感值。
- `.env.example`：配置项示例。
- `images.tar`：离线 Docker 镜像集合。
- `SHA256SUMS`：包内文件完整性清单。
- `scripts/restore-offline-bundle.sh`：标准恢复脚本。
- `docs/phase9-offline-deployment.md`：项目内部的 Phase 9 离线部署说明。
