# PostgreSQL MCP 内网部署与验收

## 1. 部署边界

- `postgres-mcp` 只使用 Docker 内部网络，不配置 `ports`，不会暴露宿主机或公网端口。
- 平台不会在控制台修改 Docker 网络。目标 PostgreSQL 位于其他 Compose 网络时，由运维人员手工把 `postgres-mcp` 容器加入该网络。
- Agent 只看到业务工具别名以及 `sql`、`schema`、`table`、`limit` 等参数。数据库地址、物理数据库名、用户名、密码、Credential ID、Connector Revision 和 Scope Revision 均由平台注入。
- 首版只允许只读查询。数据库账号只读权限、SQL AST、Resource Scope、READ ONLY 事务、超时、行数和响应体积共同构成纵深限制。
- 不增加数据库专用管理密钥；数据库管理写操作沿用平台控制面策略。

## 2. 组成

本阶段新增：

- Alembic `0017_postgresql_mcp_connector`；
- 内置 `postgresql_mcp` Connector；
- 六个 Capability：`database.list_schemas`、`database.list_tables`、`database.describe_table`、`database.preview_table`、`database.select`、`database.explain`；
- `postgres-mcp` 服务；
- 数据库连接 BFF 和四步控制台；
- Agent 多数据库 Binding；
- Hermes、Pi、DeepSeek Harness 动态 Capability Dispatcher。

## 3. 116 节点部署顺序

以下命令只在 116 的 `/opt/hermes-agent-platform` 执行。本机不执行 Docker。

### 3.1 部署前只读记录

```sh
cd /opt/hermes-agent-platform
date -Iseconds
df -hP /
docker ps -a --no-trunc --format '{{.ID}} {{.Names}} {{.Image}} {{.Status}}' \
  > /tmp/hermes-postgres-mcp-containers-before.txt
docker images --digests --format '{{.Repository}}:{{.Tag}} {{.Digest}} {{.ID}}' \
  > /tmp/hermes-postgres-mcp-images-before.txt
cp -p .env "/opt/hermes-agent-platform.env.before-postgres-mcp.$(date +%Y%m%dT%H%M%S)"
docker compose exec -T postgres pg_dump \
  -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-privileges \
  > "/opt/hermes-agent-platform.before-postgres-mcp.$(date +%Y%m%dT%H%M%S).dump"
```

备份文件包含平台数据或配置，权限应设置为 `0600`，不得放入 Git 或公开下载目录。

### 3.2 初始 Feature Flag

```text
CAPABILITY_PLATFORM_ENABLED=false
CAPABILITY_GATEWAY_ENABLED=false
CONSOLE_BFF_ENABLED=false
LEGACY_MCP_BINDING_READ_ENABLED=true
LEGACY_VECTOR_TOOL_ENABLED=true
```

`.env` 继续使用现有 `MODEL_REGISTRY_ENCRYPTION_KEY`。数据库密码只写入控制台，由平台加密存储；不得写入 Compose、Skill、Agent、文档或测试日志。

### 3.3 仅在 116 构建本阶段镜像

```sh
docker compose build \
  agent-api agent-worker mcp-gateway postgres-mcp frontend \
  hermes-runtime pi-runtime deepseek-runtime deepseek-harness-core
```

构建完成后先确认所有镜像均存在，再执行迁移：

```sh
docker compose images
docker compose run --rm --no-deps agent-api alembic upgrade 0017_postgresql_mcp_connector
docker compose run --rm --no-deps agent-api alembic current
```

### 3.4 最小范围更新

```sh
docker compose up -d --no-deps postgres-mcp
docker compose up -d --no-deps mcp-gateway
docker compose up -d --no-deps hermes-runtime pi-runtime deepseek-runtime deepseek-harness-core
docker compose up -d --no-deps agent-api agent-worker
docker compose up -d --no-deps frontend
```

不要执行 `docker compose down`，不要使用 `--remove-orphans` 或 `--volumes`。这些命令不属于本阶段部署范围。

### 3.5 健康检查与容器不变性

```sh
docker compose ps
curl -fsS http://127.0.0.1:18088/health
curl -fsS http://127.0.0.1:18089/frontend-health
docker ps -a --no-trunc --format '{{.ID}} {{.Names}} {{.Image}} {{.Status}}' \
  > /tmp/hermes-postgres-mcp-containers-after.txt
```

逐项比较部署前后的无关容器 ID，尤其是非本 Compose 项目的 `hermes`、`hermes-api`，必须保持不变。

## 4. 加入目标 PostgreSQL 网络

先由目标数据库负责人确认数据库网络和容器名，然后执行：

```sh
docker network connect <目标数据库网络> \
  hermes-agent-platform-postgres-mcp-1
docker inspect hermes-agent-platform-postgres-mcp-1 \
  --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}'
```

在控制台填写 PostgreSQL 容器名，不填 `127.0.0.1`。`postgres-mcp` 每次被重建后都需要重新执行并验证网络连接。

## 5. 控制台配置

打开“平台管理 → 数据库连接”：

1. 填写连接名称、环境、目标容器名、端口、维护库、SSL 模式和连接超时。
2. 填写只读数据库用户名和密码。保存后密码不回显。
3. 执行测试。页面会同时显示 DNS、TCP、认证、`SELECT 1`、只读事务和多数据库资源发现结果。
4. 在“数据库 → Schema → 表/视图 → 字段”树中选择范围。每个数据库保存为独立 Scope Revision。

修改 Endpoint 会先使用现有凭据测试，通过后创建新的 Connector Revision。凭据轮换会先使用新凭据测试，通过后才替换密文并关闭该连接所有 Revision 的旧连接池。停用连接后，新的数据库调用立即拒绝。

## 6. 无宿主机端口的 E2E 目标

仓库提供 `postgres-mcp-e2e` profile。它不会随正式平台启动，使用单独内部网络和单独数据卷，包含：

- `business_db`：`public.skills`、`reporting.execution_summary` 和只读视图；
- `analytics_db`：`metrics.daily_usage` 和聚合视图；
- `private_db`：故意不给测试用户 CONNECT 权限；
- `hermes_reader`：只读测试用户。

在 116 执行：

```sh
cd /opt/hermes-agent-platform
./scripts/setup-postgres-mcp-e2e-target.sh
```

页面测试配置：

```text
主机：postgres-mcp-test-db
端口：5432
维护库：postgres
用户名：hermes_reader
密码：postgres-mcp-e2e-reader
```

测试凭据只属于隔离 E2E 数据库，不得用于真实环境。

## 7. 三种 Runtime 验收

为 Hermes、Pi、DeepSeek 各创建一个 Development Agent，分别绑定：

- `business_db` Scope，工具前缀 `business_db`；
- `analytics_db` Scope，工具前缀 `analytics_db`；
- 必要的工具子集。

逐项验证：

1. `list_schemas`、`list_tables`、`describe_table`、`preview_table`、`select`、`explain`；
2. 写 CTE、`SELECT INTO`、`FOR UPDATE`、多语句和跨 Scope 查询全部拒绝；
3. Agent A 不能复用 Agent B 的 Scope，Agent 不能切换数据库地址或数据库名；
4. 结果超过行数、响应大小或超时会失败；
5. Execution Stop/Cancel 后 Token 撤销，后续工具调用拒绝；
6. Trace 和 Invocation Audit 有授权、Connector 调用和标准错误，但没有密码、Token 或内部 Header；
7. 停用连接或轮换密码后，旧连接池不再可用。

真实合同测试通过前，不得把 Runtime Feature Profile 的 `capability_gateway` 标记为 `true`。

## 8. 灰度与回滚

先保持 Feature Flag 关闭，完成旧 Agent 回归；再依次开启 Registry、Gateway 和 Console BFF，只对测试 Agent 创建 v2 Binding。回滚只恢复上一版服务镜像并关闭新 Flag，不删除 `0017` 表结构、历史 Snapshot、Trace 或 Audit。

## 9. 离线包验收

新的离线包必须包含：

- 当前源码、Compose、`0017` 迁移、本文档和 E2E 种子 SQL；
- Compose 引用的全部镜像，包括 `postgres-mcp` 和三种 Runtime 派生镜像；
- 前后端和 Runtime 已安装依赖所在镜像；
- `OFFLINE_IMAGES.txt`、内部 `SHA256SUMS`、外部归档 SHA-256。

目标内网恢复必须使用 `docker load` 和 `--pull never`，不得执行 `docker build`、`pip install`、`npm install`、`git clone` 或任何在线镜像拉取。归档不加密，但不得包含源节点 `.env`、明文数据库密码、Execution Token 或历史密钥。
