# Agent Platform 离线部署指南

本包用于在完全隔离的 Linux 节点从零恢复整套平台。部署不会拉取镜像、安装 pip/npm 依赖或访问公网。

## 1. 需要准备

- Docker Engine。
- `docker compose` 或 `docker-compose`，二选一。
- `tar`、`gzip`、`sha256sum`、`curl`。
- 内网 OpenAI Compatible 模型地址、模型名和 API Key。

不要为了部署临时升级 Docker。脚本默认不使用 `up --wait`，并会自动识别 Compose 插件或独立命令。

## 2. 解压

```sh
PACKAGE=/path/hermes-agent-platform-v2.6.0-xxxx.tar.gz
INSTALL_DIR=/opt/agent-platform

mkdir -p "$INSTALL_DIR"
tar -xzf "$PACKAGE" -C "$INSTALL_DIR" --strip-components=1
cd "$INSTALL_DIR"
```

`INSTALL_DIR` 可以换成任意空目录，脚本会根据自身位置运行，不依赖 `/opt/agent-platform`。

如需检查传输完整性：

```sh
sha256sum -c "$PACKAGE.sha256"
```

校验不一致时建议重新复制。包内恢复脚本默认会报出被修改的文件，但仍继续部署。

## 3. 生成内网配置

```sh
./scripts/configure-offline-env.sh
```

按提示输入内网模型地址、模型名和 API Key。密码不回显；其他密钥使用包内镜像在 `--network none` 环境中生成。

也可非交互执行：

```sh
OFFLINE_MODEL_ENDPOINT=http://10.20.30.40:8000/v1 \
OFFLINE_MODEL_NAME=your-model \
OFFLINE_MODEL_API_KEY='your-key' \
  ./scripts/configure-offline-env.sh
```

不要把生成的 `.env` 回传或放入代码库。

## 4. 恢复整套服务

```sh
./scripts/restore-offline-bundle.sh
```

脚本会自动完成：

1. 检查包内文件；
2. `docker load` 导入全部镜像；
3. 恢复 PostgreSQL、Redis、MinIO、Workspace、Skill 和 MCP 文件；
4. 启动 API、Worker、前端、三种 Runtime、Gateway 和 PostgreSQL MCP；
5. 使用 `docker inspect` 轮询健康状态。

源节点 `.env`、Runtime 认证文件、请求抓包和含密钥的 Runtime 配置不会进入离线包。新节点使用现场生成的密钥；恢复后如有旧模型或数据库 Connector，需在管理页重新录入凭据。

默认容器名为 `agent-*`，例如：

```text
agent-api
agent-worker
agent-frontend
agent-runtime
agent-pi-runtime
agent-deepseek-runtime
agent-postgres-mcp
agent-postgres
agent-redis
agent-minio
```

需要使用其他前缀时：

```sh
OFFLINE_PROJECT_NAME=agent-prod \
OFFLINE_CONTAINER_PREFIX=agent-prod \
  ./scripts/restore-offline-bundle.sh
```

## 5. 低版本 Docker/Compose

默认就是低版本兼容模式：

```sh
OFFLINE_COMPOSE_WAIT_MODE=manual \
OFFLINE_SERVICE_WAIT_TIMEOUT_SECONDS=600 \
  ./scripts/restore-offline-bundle.sh
```

如果机器只有 `docker-compose`，脚本会自动选择。也可强制：

```sh
OFFLINE_COMPOSE_MODE=standalone \
OFFLINE_COMPOSE_EXECUTABLE=/usr/local/bin/docker-compose \
  ./scripts/restore-offline-bundle.sh
```

如果包内文件被修改，默认 `OFFLINE_CHECKSUM_MODE=warn`：打印差异并继续。需要严格阻断时才设置：

```sh
OFFLINE_CHECKSUM_MODE=strict ./scripts/restore-offline-bundle.sh
```

## 6. 验收

```sh
docker ps --format 'table {{.Names}}\t{{.Status}}'
curl -fsS http://127.0.0.1:18088/health
curl -fsS http://127.0.0.1:18089/frontend-health
curl -fsS http://127.0.0.1:18089/health
```

前端默认对当前内网开放 `18089`；API 默认只绑定本机 `18088`。

## 7. 接入内网 PostgreSQL

目标 PostgreSQL 位于另一 Docker 网络时：

```sh
docker network connect <目标数据库网络> agent-postgres-mcp
docker inspect agent-postgres-mcp \
  --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}'
```

然后在“平台管理 → 数据库连接”中填写 PostgreSQL 容器名、端口、用户和密码，执行发现并选择允许的数据库、Schema、表和视图。不要填 `127.0.0.1`。

## 8. 失败处理

- 镜像导入失败：先重新复制离线包，不要联网拉取。
- 服务超时：增大 `OFFLINE_SERVICE_WAIT_TIMEOUT_SECONDS`，查看脚本打印的最近日志。
- 模型不可达：确认容器能访问模型 IP/容器名；容器中的 `127.0.0.1` 不是宿主机。
- `data/` 非空：恢复脚本会拒绝覆盖已有数据，请换用新目录或先做备份。

不要执行 `docker compose down -v`或全局 Docker 清理。
