# 多数据库连接支持说明

## 支持范围

平台统一通过 `agent-database-mcp` 提供只读数据库能力。Agent 只看到已绑定的工具别名、SQL、Schema、表和查询参数，不会获得数据库地址、用户名、密码、Connector ID 或 Docker 网络信息。

| 数据库 | 默认端口 | 接入方式 | 当前验证状态 |
| --- | ---: | --- | --- |
| PostgreSQL | 5432 | 原生异步驱动 | 已有真实 E2E |
| MySQL | 3306 | PyMySQL | 已完成 MySQL 8.4 真实连接、发现和只读查询 |
| MariaDB | 3306 | PyMySQL | 已完成 MariaDB 11.8 真实连接、发现和只读查询 |
| Apache Doris | 9030 | MySQL 协议 | 适配器与 SQL 方言已实现，需对目标集群做真实验收 |
| StarRocks | 9030 | MySQL 协议 | 适配器与 SQL 方言已实现，需对目标集群做真实验收 |
| SQL Server | 1433 | pymssql | 适配器已实现，需对目标版本做真实验收 |
| Oracle | 1521 | python-oracledb thin mode | 适配器已实现，需对目标版本做真实验收 |
| 达梦 DM | 5236 | 厂商 dmPython | 适配器已实现；未提供官方驱动前不能真实使用 |
| ClickHouse | 8123 | clickhouse-connect HTTP | 已完成 ClickHouse 25.8 真实连接、发现和只读查询 |
| Elasticsearch | 9200 | REST、Search、SQL API | 已完成 Elasticsearch 8.19 真实连接、发现、预览和 SQL 查询 |
| SQLite | 无 | Python 内置 sqlite3 | 已完成真实文件发现和只读查询 |

“适配器已实现”不等于目标环境已经验收。Oracle、SQL Server、Doris、StarRocks 和达梦应使用内网实际版本补做协议、权限和字符集测试后再标记为生产可用。

## 通用只读边界

- SQL 先经过方言 AST 解析，只允许单条查询语句。
- 拒绝写 CTE、DDL、DML、事务控制、锁定查询和危险函数。
- 查询对象必须落在当前 Agent 绑定的数据库资源范围内。
- 执行端继续启用数据库只读账号或只读会话、超时、最大行数和最大响应体积。
- 模型不能提交数据库地址、凭据、数据库切换参数或 Scope 标识。

数据库账号仍应由管理员在目标数据库侧配置为只读。平台 SQL 策略是第二道保护，不替代数据库自身权限。

## Elasticsearch 最小只读权限

连接账号需要：

- 集群权限：`monitor`；
- 被允许索引的权限：`read`、`view_index_metadata`、`monitor`。

其中索引级 `monitor` 用于 `_cat/indices` 资源发现，不包含写权限。运行时写请求不会作为 Agent 工具暴露，数据库账号自身也应拒绝写入。

## 达梦驱动

达梦官方 `dmPython` 不从 PyPI 下载，也不随仓库分发。制作离线包前，将与目标 Linux CPU 架构和 Python 3.12 匹配的官方 wheel 及其必需原生库放入 `drivers/dm/`，再构建 `agent-database-mcp` 镜像。

未提供驱动时，连接测试会明确返回“达梦 dmPython 官方驱动未安装”，不能把该状态视为达梦可用。

## Docker 网络

数据库 MCP 不暴露宿主机端口。目标数据库在其他 Compose 网络时，由运维人员执行：

```bash
docker network connect <目标数据库网络> agent-database-mcp
docker inspect agent-database-mcp
```

在控制台填写目标数据库的容器名或内网主机名，不填写 `127.0.0.1`。`agent-database-mcp` 被重建后，需要重新检查其目标数据库网络连接。
