# Hermes Agent Platform v2.5 离线部署手册

> 更新日期：2026-08-19
>
> 适用架构：Linux x86_64
>
> 数据库迁移版本：`0017_postgresql_mcp_connector`
>
> 默认控制台端口：`18089`

本手册对应包含 Capability Registry、PostgreSQL MCP、Hermes/Pi/DeepSeek Runtime、Agent Team、Execution/Trace/Artifact 的完整离线包。目标内网只需已有 Docker Engine、Docker Compose v2 和基础解压/校验工具；部署过程不执行镜像拉取、`docker build`、`pip install`、`npm install` 或 `git clone`。

## 1. 交付物

从下载页获取：

- `hermes-agent-platform-v2.5.0-postgresql-mcp-offline-x86_64.tar.gz`
- `hermes-agent-platform-v2.5.0-postgresql-mcp-offline-x86_64.tar.gz.sha256`
- 本 Markdown 手册

归档不加密，但不包含源节点 `.env`、模型密钥、平台管理密钥、数据库明文密码、Execution Token 或 Source Recall 上游密钥。包内包含：

- 平台源码、Compose、迁移、测试脚本和文档；
- Compose 引用的全部已构建镜像及 `OFFLINE_IMAGES.txt`；
- PostgreSQL custom dump、Redis RDB/逻辑快照、MinIO 对象和 Runtime 工作目录；
- PostgreSQL MCP 服务、`0017` 迁移、多数据库资源发现与 Scope 管理；
- `setup-postgres-mcp-e2e-target.sh` 和隔离测试数据 SQL；
- 包内 `SHA256SUMS` 与包外归档 SHA-256。

模型推理服务本身不在包内。目标内网需提供容器可访问的 OpenAI Compatible 模型接口。

## 2. 目标节点要求

- Linux x86_64；
- Docker Engine 和 `docker compose` v2；
- `tar`、`gzip`、`sha256sum`、`curl`；
- 建议至少 20 GiB 可用空间，生产数据较多时应额外预留；
- 当前用户可以运行 Docker；
- `18089` 未被占用，或在配置时改为其他端口。

检查：

```sh
uname -m
docker version
docker compose version
df -hP /opt
ss -lnt | grep -E ':(18088|18089)\b' || true
```

## 3. 下载与校验

```sh
mkdir -p ~/hermes-offline-install
cd ~/hermes-offline-install

BASE_URL='http://116.204.135.83:28086'
PACKAGE='hermes-agent-platform-v2.5.0-postgresql-mcp-offline-x86_64.tar.gz'

curl -fL -C - -O "$BASE_URL/$PACKAGE"
curl -fLO "$BASE_URL/$PACKAGE.sha256"
sha256sum -c "$PACKAGE.sha256"
```

必须看到：

```text
hermes-agent-platform-v2.5.0-postgresql-mcp-offline-x86_64.tar.gz: OK
```

## 4. 解压到新目录

不要覆盖已有平台目录，不要为继续安装而直接删除未知数据。

```sh
sudo install -d -m 0755 /opt/hermes-agent-platform
sudo tar -xzf "$HOME/hermes-offline-install/$PACKAGE" \
  -C /opt/hermes-agent-platform \
  --strip-components=1
sudo chown -R "$(id -u):$(id -g)" /opt/hermes-agent-platform
cd /opt/hermes-agent-platform

test -f images.tar
test -f OFFLINE_IMAGES.txt
test -f SHA256SUMS
test -f .env.example
test -x scripts/configure-offline-env.sh
test -x scripts/restore-offline-bundle.sh
sha256sum -c SHA256SUMS
```

归档内故意没有 `.env`。

## 5. 生成内网配置

执行：

```sh
cd /opt/hermes-agent-platform
./scripts/configure-offline-env.sh
```

脚本会：

1. 从包内 `images.tar` 执行 `docker load`；
2. 使用包内 Agent API 镜像并通过 `--network none` 在本地生成新密钥；
3. 询问内网模型地址、模型名和 API Key，API Key 输入不回显；
4. 从 `.env.example` 生成权限为 `0600` 的新 `.env`；
5. 默认启用 Capability Platform、Capability Gateway 和 Console BFF；
6. 默认关闭 Source Recall，上游地址和上游 Key 保持为空；
7. 生成 Source Recall 内部网关 Key，但不打印其值。

模型地址必须从容器内可达。不要填写 `127.0.0.1`，除非模型服务与调用容器在同一网络命名空间。常见形式：

```text
http://model-service:8000/v1
http://10.20.30.40:8000/v1
```

配置后只核对非敏感开关，不要把 `.env` 内容复制到聊天、工单或公开日志：

```sh
chmod 600 .env
awk -F= '$1 ~ /^(CAPABILITY_PLATFORM_ENABLED|CAPABILITY_GATEWAY_ENABLED|CONSOLE_BFF_ENABLED|SOURCE_RECALL_ENABLED)$/ {print}' .env
```

期望前三项为 `true`，`SOURCE_RECALL_ENABLED=false`。

## 6. 执行离线恢复

```sh
cd /opt/hermes-agent-platform

OFFLINE_PROJECT_NAME=hermes-agent-platform \
OFFLINE_AGENT_API_PORT=18088 \
OFFLINE_FRONTEND_PORT=18089 \
  ./scripts/restore-offline-bundle.sh
```

恢复脚本会校验包内文件、确认镜像已加载、以 `--pull never` 启动服务，恢复 PostgreSQL、Redis、MinIO 和 Runtime 数据，并检查 Agent API、前端、Pi 与 DeepSeek Runtime。恢复期间不访问公网。

源节点 Connector Credential 和模型 API Key 在 PostgreSQL dump 中只有密文，且离线包不带源 `MODEL_REGISTRY_ENCRYPTION_KEY`。使用新主密钥时，恢复后需要在“模型管理”和“数据库连接”页面重新录入对应凭据；API 不会回显旧密码。

## 7. 接入目标 PostgreSQL

`postgres-mcp` 没有宿主机端口。目标 PostgreSQL 位于其他 Docker 网络时，由运维人员手工连接网络：

```sh
docker network connect <目标数据库网络> \
  hermes-agent-platform-postgres-mcp-1

docker inspect hermes-agent-platform-postgres-mcp-1 \
  --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}'
```

每次重建 `postgres-mcp` 容器后都要重新执行并验证。控制台中的主机填写目标 PostgreSQL 容器名，不填 `127.0.0.1`。

打开“平台管理 → 数据库连接”，按四步完成：

1. 基础连接；
2. 凭据；
3. 连接测试和多数据库资源发现；
4. 为每个数据库选择 Schema、表/视图、字段权限和只读限制。

保存后，在 Agent 的“能力与资源”中绑定数据库 Scope 和工具别名前缀。模型只能看到工具别名与业务参数，看不到地址、密码、Connection ID、Credential ID 或 Docker 网络。

## 8. 部署验收

### 8.1 容器与健康

```sh
cd /opt/hermes-agent-platform
docker compose -p hermes-agent-platform ps
curl -fsS http://127.0.0.1:18088/health
curl -fsS http://127.0.0.1:18089/frontend-health
curl -fsS http://127.0.0.1:18089/health
```

`hermes-init` 和 `minio-init` 是一次性服务，其余核心服务应处于运行或健康状态。

### 8.2 迁移版本

```sh
set -a
. ./.env
set +a
docker compose -p hermes-agent-platform exec -T postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc \
  'select version_num from alembic_version;'
```

期望：

```text
0017_postgresql_mcp_connector
```

### 8.3 Runtime 与数据库能力

至少验证：

- Hermes、Pi、DeepSeek Runtime 均在线；
- 创建数据库连接后可发现数据库、Schema、表、视图和字段；
- Agent 可调用绑定的 `*_db_select`，并只能访问绑定 Scope；
- 写 CTE、`SELECT INTO`、`FOR UPDATE`、多语句和跨 Scope 查询被拒绝；
- Trace 和 Invocation Audit 有调用记录，但没有密码或 Token；
- 连接停用后，Agent 后续数据库调用立即失败；
- PostgreSQL 不映射宿主机端口仍可正常访问。

## 9. Source Recall（可选）

完全隔离环境默认：

```text
SOURCE_RECALL_ENABLED=false
SOURCE_RECALL_UPSTREAM_ENDPOINT=
SOURCE_RECALL_UPSTREAM_API_KEY=
```

这不会影响数据库能力、Skill、文件 MCP 或模型调用。若以后在内网提供召回接口，只在目标节点 `.env` 或 Connector Credential 中配置，随后按受控变更启用；不要把 Key 写入 Skill、Agent、文档或离线包。

## 10. 常见问题

### 数据目录非空

`restore-offline-bundle.sh` 会拒绝覆盖非空 `data/`。请改用新目录，或先完成备份并明确已有目录归属。不要直接删除。

### 模型不可达

检查容器内 DNS/路由和模型地址；容器内的 `127.0.0.1` 通常不是 Docker 主机。

```sh
docker compose logs --tail=200 model-gateway hermes-runtime pi-runtime deepseek-runtime
```

### PostgreSQL 容器名解析失败

确认 `postgres-mcp` 已加入目标数据库网络，并确认控制台填写的是目标 PostgreSQL 容器名。

### 不允许拉取镜像

恢复命令已经使用 `--pull never`。若出现镜像缺失，说明 `images.tar` 不完整或镜像未成功 `docker load`，不要临时联网拉取；重新校验归档和 `OFFLINE_IMAGES.txt`。

## 11. 运维边界

- 不要执行 `docker compose down -v` 或不明范围的 Docker 清理；
- `.env`、数据库备份和离线包只放在受控存储；
- 控制台端口只在可信内网开放；本方案不建设公网 TLS、域名或证书；
- 内网生成的密钥不得回传到下载服务器；
- 下载完成后应将离线包转移到内网制品库，`28086` 只作为临时下载入口。

## 12. 关键文件

- `docker-compose.yml`：平台编排；
- `.env.example`：无真实密钥的模板；
- `images.tar`：全部离线镜像；
- `OFFLINE_IMAGES.txt`：镜像清单；
- `SHA256SUMS`：包内文件校验；
- `scripts/configure-offline-env.sh`：离线生成新 `.env`；
- `scripts/restore-offline-bundle.sh`：标准恢复；
- `scripts/setup-postgres-mcp-e2e-target.sh`：可选隔离测试库；
- `docs/postgresql-mcp-deployment.md`：PostgreSQL MCP 详细说明；
- `docs/phase9-offline-deployment.md`：离线迁移设计与验证说明。
