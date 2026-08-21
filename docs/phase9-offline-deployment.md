# Phase 9 离线部署与迁移

## 1. 离线包内容

`create-offline-bundle.sh` 在已运行的平台节点生成单个 `.tar.gz` 交付包及外部 SHA-256 文件。包内包含：

- 当前平台源码、Compose、Skill、Demo 配置和运维脚本；
- Compose 引用的全部 Docker 镜像，统一保存在 `images.tar`；
- 脱敏 `.env.example` 和目标节点离线配置脚本，不包含源节点 `.env`；
- 模型注册表和 Connector Credential 的加密密文，但不包含源节点 `MODEL_REGISTRY_ENCRYPTION_KEY`；
- PostgreSQL custom-format 逻辑备份；
- Redis RDB 与支持 TTL 的逻辑键快照；Stream 会恢复条目和 Consumer Group 游标，但不恢复源节点 pending consumer 的所有权，避免离线节点错误续跑源节点处理中任务；
- MinIO `artifacts`、`knowledge` 两个 bucket 的对象镜像；
- 已脱敏的 Runtime 能力数据、工作目录和 MCP 只读文件；Runtime 配置、认证文件、请求抓包、日志、缓存和状态库不进包；
- 已固化官方 `@earendil-works/pi-agent-core 0.84.2` 依赖的 `pi-runtime` 镜像；
- 已固化官方 DeepSeek Harness npm `0.1.0-rc.6` 依赖和锁文件的 DeepSeek Runtime 镜像、隔离网关和 Harness JSONL Session 数据目录；
- PostgreSQL MCP 镜像、`0017` 迁移、数据库资源发现/Scope 管理前后端和隔离 E2E 种子数据；
- 所有内部文件的 `SHA256SUMS` 与镜像清单。

离线包不包含源节点的模型、数据库、Redis、MinIO、Runtime 或签名密钥。脚本仍以 `0600` 创建归档和校验文件，归档不加密，但不得上传到公开制品库或提交到 Git。

目标节点默认生成新的 `MODEL_REGISTRY_ENCRYPTION_KEY`，因此备份内已有模型 API Key 和 Connector Credential 密文不可在目标节点解密。恢复后必须在模型管理页面重新录入模型 API Key，并在数据库连接/Connector 页面轮换凭据。历史 Snapshot、Trace 和 Audit 保留，但旧密文不会回显。若必须保留既有密文，可通过受控的独立渠道在执行配置脚本时设置 `OFFLINE_MODEL_REGISTRY_ENCRYPTION_KEY`；该主密钥仍不得放进离线归档、命令日志或公开制品库。

## 2. 在源节点导出

在 `/opt/hermes-agent-platform` 加载 `.env` 后执行：

```sh
./scripts/create-offline-bundle.sh /opt/hermes-agent-platform/dist
```

脚本使用 `pg_dump`、Redis RDB 和 MinIO S3 接口获取一致、可迁移的数据，不复制运行中的 PostgreSQL/Redis/MinIO 原始存储目录。

## 3. 在新内网节点导入

新节点只需要预装兼容的 Docker Engine、`docker compose` 插件或 `docker-compose` 独立命令，以及 `tar`、`gzip`、`sha256sum` 和 `curl`。不需要 `up --wait`、`config --quiet` 或 `run --pull`；恢复脚本默认使用 `docker inspect` 手动健康轮询。复制 `.tar.gz` 与同名 `.sha256` 后：

```sh
sha256sum -c hermes-agent-platform-v2.6.0-*.tar.gz.sha256
mkdir -p /opt/agent-platform
tar -xzf hermes-agent-platform-v2.6.0-*.tar.gz \
  -C /opt/agent-platform --strip-components=1
cd /opt/agent-platform
./scripts/configure-offline-env.sh
./scripts/restore-offline-bundle.sh
```

配置脚本先执行 `docker load`，再通过 `--network none` 的包内镜像生成目标节点新密钥，并现场接收内网模型地址、模型名和 API Key；这些值不会打印到终端。恢复脚本随后完成内部校验、镜像导入与存在性检查、持久数据恢复、服务启动和 API 健康检查。校验和不一致默认会报告并继续；镜像本身无法导入或缺失时仍会在启动前失败，不会在线补拉镜像。默认容器前缀为 `agent-`。

## 4. 116 隔离验收

Phase 9 在 116 使用以下完全独立的验证边界模拟新节点：

- 目录：`/opt/agent-platform-offline-verify`；
- Compose 项目：`agent-offline-verify`；
- 容器前缀：`agent-verify-`；
- Agent API：`127.0.0.1:28088`。
- 管理控制台：`127.0.0.1:28080`。

执行：

```sh
./tests/phase9_offline_deployment.sh /absolute/path/to/hermes-agent-platform-v1.0.0-*.tar.gz
```

测试强制设置 `OFFLINE_COMPOSE_WAIT_MODE=manual`，不调用 `up --wait`。它验证归档内外校验和、镜像导入、十六个长期服务状态与健康检查、Pi/DeepSeek Runtime 自动注册与健康检查、前端静态页面与 API 同源代理、PostgreSQL/Redis/MinIO/文件/Harness Session 数据迁移，以及恢复后的 Knowledge Analyst 真实多源分析。测试还比较原 `hermes-agent-platform` 容器 ID，确保整个过程没有重建原部署。成功后只删除隔离验证项目和验证目录，保留原部署与离线包。
