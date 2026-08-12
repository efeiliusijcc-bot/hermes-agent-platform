# Phase 9 离线部署与迁移

## 1. 离线包内容

`create-offline-bundle.sh` 在已运行的平台节点生成单个 `.tar.gz` 交付包及外部 SHA-256 文件。包内包含：

- 当前平台源码、Compose、Skill、Demo 配置和运维脚本；
- Compose 引用的全部 Docker 镜像，统一保存在 `images.tar`；
- 运行 `.env` 配置；
- PostgreSQL custom-format 逻辑备份；
- Redis RDB 与支持 TTL 的逻辑键快照；
- MinIO `artifacts`、`knowledge` 两个 bucket 的对象镜像；
- Hermes 数据目录、工作目录和 MCP 只读文件；
- 所有内部文件的 `SHA256SUMS` 与镜像清单。

离线包包含模型、数据库、Redis 和 MinIO 密钥，必须按敏感配置文件管理。脚本以 `0600` 创建归档和校验文件，不得上传到公开制品库或提交到 Git。

## 2. 在源节点导出

在 `/opt/hermes-agent-platform` 加载 `.env` 后执行：

```sh
./scripts/create-offline-bundle.sh /opt/hermes-agent-platform/dist
```

脚本使用 `pg_dump`、Redis RDB 和 MinIO S3 接口获取一致、可迁移的数据，不复制运行中的 PostgreSQL/Redis/MinIO 原始存储目录。

## 3. 在新内网节点导入

新节点只需要预装兼容的 Docker Engine、Docker Compose、`tar`、`gzip`、`sha256sum` 和 `curl`。复制 `.tar.gz` 与同名 `.sha256` 后：

```sh
sha256sum -c hermes-agent-platform-v1.0.0-*.tar.gz.sha256
mkdir -p /opt/hermes-agent-platform
tar -xzf hermes-agent-platform-v1.0.0-*.tar.gz \
  -C /opt/hermes-agent-platform --strip-components=1
cd /opt/hermes-agent-platform
./scripts/restore-offline-bundle.sh
```

恢复脚本依次完成：内部校验、`docker load`、持久目录准备、Redis RDB 放置与逻辑键恢复、PostgreSQL 恢复、MinIO 对象导入、服务启动和 API 健康检查。Redis 7 在 AOF 模式下不会直接采用外部 RDB，因此 RDB 作为完整备份保留，运行恢复使用带类型和 TTL 的逻辑快照。

## 4. 116 隔离验收

Phase 9 在 116 使用以下完全独立的验证边界模拟新节点：

- 目录：`/opt/hermes-agent-platform-offline-verify`；
- Compose 项目：`hermes-agent-platform-offline-verify`；
- 网络：`hermes-agent-platform-offline-verify-internal`、`hermes-agent-platform-offline-verify-edge`；
- Agent API：`127.0.0.1:28088`。
- 管理控制台：`127.0.0.1:28080`。

执行：

```sh
./tests/phase9_offline_deployment.sh /absolute/path/to/hermes-agent-platform-v1.0.0-*.tar.gz
```

测试验证归档内外校验和、镜像导入、九个长期服务健康、前端静态页面与 API 同源代理、PostgreSQL/Redis/MinIO/文件数据迁移，以及恢复后的 Knowledge Analyst 真实多源分析。测试还比较原 `hermes-agent-platform` 容器 ID，确保整个过程没有重建原部署。成功后只删除隔离验证项目和验证目录，保留原部署与离线包。
