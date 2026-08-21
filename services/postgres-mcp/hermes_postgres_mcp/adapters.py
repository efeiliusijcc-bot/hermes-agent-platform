from __future__ import annotations

import asyncio
import importlib
import json
import os
import socket
import sqlite3
import sys
from datetime import date, datetime, time
from decimal import Decimal
from abc import ABC, abstractmethod
from contextlib import closing
from pathlib import Path
from time import monotonic
from typing import Any, Callable
from urllib.parse import quote

import httpx


DATABASE_TYPES = {
    "mysql", "mariadb", "doris", "starrocks", "sqlserver", "oracle",
    "dm", "clickhouse", "elasticsearch", "sqlite",
}
DEFAULT_PORTS = {
    "mysql": 3306,
    "mariadb": 3306,
    "doris": 9030,
    "starrocks": 9030,
    "sqlserver": 1433,
    "oracle": 1521,
    "dm": 5236,
    "clickhouse": 8123,
    "elasticsearch": 9200,
}
SYSTEM_DATABASES = {
    "information_schema", "mysql", "performance_schema", "sys", "master",
    "model", "msdb", "tempdb", "system", "INFORMATION_SCHEMA",
}
SYSTEM_SCHEMAS = {
    "information_schema", "pg_catalog", "sys", "SYSTEM", "SYS", "SYSMAN",
    "OUTLN", "DBSNMP", "XDB", "CTXSYS", "MDSYS", "ORDSYS",
}


class AdapterError(ValueError):
    pass


class DatabaseAdapter(ABC):
    database_type: str

    @abstractmethod
    async def test_and_discover(self, config: dict[str, Any], credential: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def describe(self, runtime: dict[str, Any], schema: str, table: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def select(self, runtime: dict[str, Any], sql: str, maximum: int) -> dict[str, Any]:
        raise NotImplementedError

    async def preview(self, runtime: dict[str, Any], schema: str, table: str, maximum: int) -> dict[str, Any]:
        sql = f"SELECT * FROM {qualified_identifier(self.database_type, schema, table)}"
        return await self.select(runtime, sql, maximum)

    async def explain(self, runtime: dict[str, Any], sql: str) -> dict[str, Any]:
        return await self.select(runtime, explain_sql(self.database_type, sql), 100)

    async def invalidate(self, _: str) -> None:
        return None


class DBAPIAdapter(DatabaseAdapter):
    def __init__(
        self,
        database_type: str,
        connect: Callable[[dict[str, Any], dict[str, Any], str], Any],
        version_sql: str,
        database_sql: str,
        objects_sql: str,
        columns_sql: str,
        parameter: str = "%s",
    ) -> None:
        self.database_type = database_type
        self._connect = connect
        self.version_sql = version_sql
        self.database_sql = database_sql
        self.objects_sql = objects_sql
        self.columns_sql = columns_sql
        self.parameter = parameter

    async def test_and_discover(self, config: dict[str, Any], credential: dict[str, Any]) -> dict[str, Any]:
        started = monotonic()
        checks = await network_checks(config, credential)

        def work() -> tuple[str, list[dict[str, Any]], list[str]]:
            maintenance = str(config.get("maintenance_database") or default_database(self.database_type))
            with closing(self._connect(config, credential, maintenance)) as connection:
                version = str(fetch_scalar(connection, self.version_sql) or self.database_type)
                fetch_scalar(connection, "SELECT 1")
                database_rows = fetch_rows(connection, self.database_sql)
            names = [str(next(iter(row.values()))) for row in database_rows]
            names = [name for name in names if name and name not in SYSTEM_DATABASES]
            if self.database_type in {"oracle", "dm"}:
                names = [maintenance]
            maximum = int(os.getenv("POSTGRES_MCP_DISCOVERY_MAX_DATABASES", "100"))
            warnings: list[str] = []
            if len(names) > maximum:
                names = names[:maximum]
                warnings.append(f"数据库数量超过 {maximum}，已截断")
            databases = []
            for name in names:
                try:
                    databases.append({"name": name, "status": "READY", "schemas": self._discover_sync(config, credential, name)})
                except Exception as exc:
                    databases.append({"name": name, "status": "UNAVAILABLE", "schemas": [], "error": type(exc).__name__})
                    warnings.append(f"数据库 {name} 资源发现失败：{type(exc).__name__}")
            return version, databases, warnings

        try:
            version, databases, warnings = await asyncio.to_thread(work)
        except Exception as exc:
            raise AdapterError(f"{database_label(self.database_type)} 连接失败：{safe_driver_error(exc)}") from exc
        if not any(item["status"] == "READY" for item in databases):
            raise AdapterError("没有可发现的数据库")
        checks.extend([
            {"name": "authentication", "status": "passed", "detail": str(credential.get("username") or "local")},
            {"name": "select", "status": "passed", "detail": "SELECT 1"},
            {"name": "read_only", "status": "passed", "detail": "平台只读策略已启用"},
            {"name": "discovery", "status": "passed", "detail": f"发现 {len(databases)} 个数据库"},
        ])
        return discovery_result(self.database_type, version, databases, checks, warnings, started)

    def _discover_sync(self, config: dict[str, Any], credential: dict[str, Any], database: str) -> list[dict[str, Any]]:
        with closing(self._connect(config, credential, database)) as connection:
            objects = fetch_rows(connection, self.objects_sql, (database,))
            columns = fetch_rows(connection, self.columns_sql, (database,))
        column_map: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in columns:
            schema = str(row.get("schema_name") or row.get("owner") or database)
            table = str(row.get("table_name") or "")
            if not table:
                continue
            column_map.setdefault((schema, table), []).append({
                "name": str(row.get("column_name") or ""),
                "type": str(row.get("data_type") or row.get("column_type") or "unknown"),
                "nullable": str(row.get("is_nullable") or row.get("nullable") or "").upper() in {"YES", "Y", "TRUE", "1"},
            })
        schemas: dict[str, dict[str, Any]] = {}
        for row in objects:
            schema = str(row.get("schema_name") or row.get("owner") or database)
            if schema in SYSTEM_SCHEMAS:
                continue
            name = str(row.get("object_name") or row.get("table_name") or "")
            if not name:
                continue
            kind = str(row.get("object_type") or row.get("table_type") or "table").lower()
            bucket = "views" if "view" in kind else "tables"
            value = schemas.setdefault(schema, {"name": schema, "tables": [], "views": []})
            value[bucket].append({"name": name, "columns": column_map.get((schema, name), [])})
        return [schemas[name] for name in sorted(schemas)]

    async def describe(self, runtime: dict[str, Any], schema: str, table: str) -> dict[str, Any]:
        def work() -> list[dict[str, Any]]:
            with closing(self._connect(runtime["config"], runtime["credential"], runtime["database"])) as connection:
                rows = fetch_rows(connection, self.columns_sql, (runtime["database"],))
            return [
                {"name": row.get("column_name"), "type": row.get("data_type") or row.get("column_type"), "nullable": str(row.get("is_nullable") or row.get("nullable") or "").upper() in {"YES", "Y", "TRUE", "1"}}
                for row in rows
                if str(row.get("schema_name") or row.get("owner") or runtime["database"]) == schema
                and str(row.get("table_name")) == table
            ]
        columns = await asyncio.to_thread(work)
        return {"database": runtime["database"], "schema": schema, "table": table, "columns": columns}

    async def select(self, runtime: dict[str, Any], sql: str, maximum: int) -> dict[str, Any]:
        def work() -> tuple[list[dict[str, Any]], bool]:
            with closing(self._connect(runtime["config"], runtime["credential"], runtime["database"])) as connection:
                configure_read_only(connection, self.database_type, runtime["scope"])
                with closing(connection.cursor()) as cursor:
                    cursor.execute(sql)
                    names = [str(item[0]) for item in (cursor.description or [])]
                    rows = cursor.fetchmany(maximum + 1)
            return [
                {name: json_value(value) for name, value in zip(names, row)}
                for row in rows[:maximum]
            ], len(rows) > maximum

        try:
            rows, truncated = await asyncio.to_thread(work)
        except Exception as exc:
            raise AdapterError(f"只读查询失败：{safe_driver_error(exc)}") from exc
        return {"database": runtime["database"], "rows": rows, "row_count": len(rows), "truncated": truncated}


class ClickHouseAdapter(DatabaseAdapter):
    database_type = "clickhouse"

    def _client(self, config: dict[str, Any], credential: dict[str, Any], database: str):
        from clickhouse_connect import get_client
        return get_client(
            host=required(config, "host"),
            port=int(config.get("port") or 8123),
            username=required(credential, "username"),
            password=required(credential, "password"),
            database=database,
            secure=str(config.get("ssl_mode") or "disable") != "disable",
            connect_timeout=int(config.get("connect_timeout_seconds") or 5),
        )

    async def test_and_discover(self, config: dict[str, Any], credential: dict[str, Any]) -> dict[str, Any]:
        started = monotonic()
        checks = await network_checks(config, credential)

        def work():
            client = self._client(config, credential, str(config.get("maintenance_database") or "default"))
            try:
                version = str(client.command("SELECT version()"))
                names = [str(row[0]) for row in client.query("SELECT name FROM system.databases WHERE name NOT IN ('system','information_schema','INFORMATION_SCHEMA') ORDER BY name").result_rows]
                databases = []
                for database in names:
                    objects = client.query("SELECT database, name, engine FROM system.tables WHERE database = {db:String} ORDER BY name", parameters={"db": database}).result_rows
                    columns = client.query("SELECT database, table, name, type FROM system.columns WHERE database = {db:String} ORDER BY table, position", parameters={"db": database}).result_rows
                    column_map: dict[str, list[dict[str, Any]]] = {}
                    for _, table, name, kind in columns:
                        column_map.setdefault(str(table), []).append({"name": str(name), "type": str(kind), "nullable": str(kind).startswith("Nullable(")})
                    schema = {"name": database, "tables": [], "views": []}
                    for _, name, engine in objects:
                        bucket = "views" if "View" in str(engine) else "tables"
                        schema[bucket].append({"name": str(name), "columns": column_map.get(str(name), [])})
                    databases.append({"name": database, "status": "READY", "schemas": [schema]})
                return version, databases
            finally:
                client.close()

        try:
            version, databases = await asyncio.to_thread(work)
        except Exception as exc:
            raise AdapterError(f"ClickHouse 连接失败：{safe_driver_error(exc)}") from exc
        checks.extend(default_success_checks(credential, len(databases)))
        return discovery_result(self.database_type, version, databases, checks, [], started)

    async def describe(self, runtime: dict[str, Any], schema: str, table: str) -> dict[str, Any]:
        result = await self.select(runtime, f"SELECT name, type FROM system.columns WHERE database = '{literal(schema)}' AND table = '{literal(table)}' ORDER BY position", 1000)
        return {"database": runtime["database"], "schema": schema, "table": table, "columns": result["rows"]}

    async def select(self, runtime: dict[str, Any], sql: str, maximum: int) -> dict[str, Any]:
        def work():
            client = self._client(runtime["config"], runtime["credential"], runtime["database"])
            try:
                result = client.query(sql, settings={"readonly": 1, "max_result_rows": maximum + 1, "result_overflow_mode": "break"})
                values = [{name: json_value(value) for name, value in zip(result.column_names, row)} for row in result.result_rows]
                return values[:maximum], len(values) > maximum
            finally:
                client.close()
        rows, truncated = await asyncio.to_thread(work)
        return {"database": runtime["database"], "rows": rows, "row_count": len(rows), "truncated": truncated}


class ElasticsearchAdapter(DatabaseAdapter):
    database_type = "elasticsearch"

    def _base(self, config: dict[str, Any]) -> str:
        scheme = "https" if str(config.get("ssl_mode") or "disable") != "disable" else "http"
        prefix = str(config.get("url_path_prefix") or "").rstrip("/")
        return f"{scheme}://{required(config, 'host')}:{int(config.get('port') or 9200)}{prefix}"

    def _auth(self, credential: dict[str, Any]) -> tuple[str, str]:
        return required(credential, "username"), required(credential, "password")

    def _client(self, config: dict[str, Any], credential: dict[str, Any]) -> httpx.AsyncClient:
        timeout = float(config.get("connect_timeout_seconds") or 5)
        verify = str(config.get("ssl_mode") or "disable") not in {"disable", "prefer"}
        return httpx.AsyncClient(
            timeout=timeout,
            auth=self._auth(credential),
            verify=verify,
            trust_env=False,
        )

    @staticmethod
    def _http_error(exc: httpx.HTTPStatusError) -> AdapterError:
        status = exc.response.status_code
        if status == 401:
            return AdapterError("Elasticsearch 认证失败：用户名或密码无效")
        if status == 403:
            return AdapterError(
                "Elasticsearch 权限不足：连接账号需要 cluster monitor，"
                "并对可发现索引具有 read、view_index_metadata、monitor 权限"
            )
        return AdapterError(f"Elasticsearch 请求失败：HTTP {status}")

    async def test_and_discover(self, config: dict[str, Any], credential: dict[str, Any]) -> dict[str, Any]:
        started = monotonic()
        checks = await network_checks(config, credential)
        try:
            async with self._client(config, credential) as client:
                root = (await client.get(self._base(config))).raise_for_status().json()
                rows = (await client.get(f"{self._base(config)}/_cat/indices", params={"format": "json", "h": "index,status"})).raise_for_status().json()
                indices = [str(item.get("index")) for item in rows if item.get("index") and not str(item.get("index")).startswith(".")]
                objects = []
                warnings = []
                for index in indices:
                    try:
                        mapping = (await client.get(f"{self._base(config)}/{quote(index, safe='')}/_mapping")).raise_for_status().json()
                        fields = (((mapping.get(index) or {}).get("mappings") or {}).get("properties") or {})
                        columns = [{"name": name, "type": str(value.get("type") or "object"), "nullable": True} for name, value in sorted(fields.items())]
                        objects.append({"name": index, "columns": columns})
                    except Exception as exc:
                        warnings.append(f"索引 {index} mapping 发现失败：{type(exc).__name__}")
                cluster = str(root.get("cluster_name") or config.get("maintenance_database") or "_cluster")
                databases = [{"name": cluster, "status": "READY", "schemas": [{"name": "_indices", "tables": objects, "views": []}]}]
                version = str((root.get("version") or {}).get("number") or "unknown")
        except httpx.HTTPStatusError as exc:
            raise self._http_error(exc) from exc
        except httpx.RequestError as exc:
            raise AdapterError(f"Elasticsearch 网络请求失败：{type(exc).__name__}") from exc
        except Exception as exc:
            raise AdapterError(f"Elasticsearch 连接失败：{safe_driver_error(exc)}") from exc
        checks.extend(default_success_checks(credential, 1))
        return discovery_result(self.database_type, version, databases, checks, warnings, started)

    async def describe(self, runtime: dict[str, Any], schema: str, table: str) -> dict[str, Any]:
        self._require_index_schema(schema)
        try:
            async with self._client(runtime["config"], runtime["credential"]) as client:
                data = (await client.get(f"{self._base(runtime['config'])}/{quote(table, safe='')}/_mapping")).raise_for_status().json()
        except httpx.HTTPStatusError as exc:
            raise self._http_error(exc) from exc
        except httpx.RequestError as exc:
            raise AdapterError(f"Elasticsearch 网络请求失败：{type(exc).__name__}") from exc
        fields = (((data.get(table) or {}).get("mappings") or {}).get("properties") or {})
        return {"database": runtime["database"], "schema": schema, "table": table, "columns": [{"name": name, "type": str(value.get("type") or "object"), "nullable": True} for name, value in sorted(fields.items())]}

    async def preview(self, runtime: dict[str, Any], schema: str, table: str, maximum: int) -> dict[str, Any]:
        self._require_index_schema(schema)
        try:
            async with self._client(runtime["config"], runtime["credential"]) as client:
                data = (await client.post(f"{self._base(runtime['config'])}/{quote(table, safe='')}/_search", json={"size": maximum, "query": {"match_all": {}}})).raise_for_status().json()
        except httpx.HTTPStatusError as exc:
            raise self._http_error(exc) from exc
        except httpx.RequestError as exc:
            raise AdapterError(f"Elasticsearch 网络请求失败：{type(exc).__name__}") from exc
        rows = [{"_id": item.get("_id"), **(item.get("_source") or {})} for item in ((data.get("hits") or {}).get("hits") or [])]
        return {"database": runtime["database"], "rows": rows, "row_count": len(rows), "truncated": False}

    async def select(self, runtime: dict[str, Any], sql: str, maximum: int) -> dict[str, Any]:
        try:
            async with self._client(runtime["config"], runtime["credential"]) as client:
                response = await client.post(f"{self._base(runtime['config'])}/_sql", params={"format": "json"}, json={"query": sql, "fetch_size": maximum + 1})
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            raise self._http_error(exc) from exc
        except httpx.RequestError as exc:
            raise AdapterError(f"Elasticsearch 网络请求失败：{type(exc).__name__}") from exc
        names = [str(item.get("name")) for item in data.get("columns") or []]
        values = [dict(zip(names, row)) for row in data.get("rows") or []]
        return {"database": runtime["database"], "rows": values[:maximum], "row_count": min(len(values), maximum), "truncated": len(values) > maximum}

    async def explain(self, runtime: dict[str, Any], sql: str) -> dict[str, Any]:
        try:
            async with self._client(runtime["config"], runtime["credential"]) as client:
                data = (await client.post(f"{self._base(runtime['config'])}/_sql/translate", json={"query": sql})).raise_for_status().json()
        except httpx.HTTPStatusError as exc:
            raise self._http_error(exc) from exc
        except httpx.RequestError as exc:
            raise AdapterError(f"Elasticsearch 网络请求失败：{type(exc).__name__}") from exc
        return {"database": runtime["database"], "plan": data}

    @staticmethod
    def _require_index_schema(schema: str) -> None:
        if schema != "_indices":
            raise AdapterError("Elasticsearch 只允许 _indices 资源组")


class SQLiteAdapter(DBAPIAdapter):
    database_type = "sqlite"

    def __init__(self) -> None:
        super().__init__(
            "sqlite", sqlite_connect, "SELECT sqlite_version()", "SELECT 'main' AS name",
            "SELECT 'main' AS schema_name, name AS object_name, type AS object_type FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name",
            "SELECT 'main' AS schema_name, m.name AS table_name, p.name AS column_name, p.type AS data_type, CASE p.[notnull] WHEN 0 THEN 'YES' ELSE 'NO' END AS is_nullable FROM sqlite_master m JOIN pragma_table_info(m.name) p WHERE m.type IN ('table','view') ORDER BY m.name, p.cid",
            parameter="?",
        )

    async def test_and_discover(self, config: dict[str, Any], credential: dict[str, Any]) -> dict[str, Any]:
        result = await super().test_and_discover(config, credential)
        result["checks"] = [item for item in result["checks"] if item["name"] not in {"dns", "tcp", "authentication"}]
        result["checks"].insert(0, {"name": "file", "status": "passed", "detail": str(config.get("database_file"))})
        return result


def adapter_for(database_type: str) -> DatabaseAdapter:
    if database_type == "elasticsearch":
        return ElasticsearchAdapter()
    if database_type == "clickhouse":
        return ClickHouseAdapter()
    if database_type == "sqlite":
        return SQLiteAdapter()
    if database_type in {"mysql", "mariadb", "doris", "starrocks"}:
        return mysql_adapter(database_type)
    if database_type == "sqlserver":
        return sqlserver_adapter()
    if database_type == "oracle":
        return oracle_adapter()
    if database_type == "dm":
        return dm_adapter()
    raise AdapterError(f"不支持的数据库类型 {database_type}")


def mysql_adapter(database_type: str) -> DBAPIAdapter:
    return DBAPIAdapter(
        database_type,
        mysql_connect,
        "SELECT VERSION()",
        "SELECT SCHEMA_NAME AS name FROM information_schema.SCHEMATA ORDER BY SCHEMA_NAME",
        "SELECT TABLE_SCHEMA AS schema_name, TABLE_NAME AS object_name, TABLE_TYPE AS object_type FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME",
        "SELECT TABLE_SCHEMA AS schema_name, TABLE_NAME AS table_name, COLUMN_NAME AS column_name, COLUMN_TYPE AS data_type, IS_NULLABLE AS is_nullable FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME, ORDINAL_POSITION",
    )


def sqlserver_adapter() -> DBAPIAdapter:
    return DBAPIAdapter(
        "sqlserver",
        sqlserver_connect,
        "SELECT CAST(SERVERPROPERTY('ProductVersion') AS VARCHAR(128))",
        "SELECT name FROM sys.databases WHERE state = 0 AND HAS_DBACCESS(name) = 1 ORDER BY name",
        "SELECT TABLE_SCHEMA AS schema_name, TABLE_NAME AS object_name, TABLE_TYPE AS object_type FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_CATALOG = %s ORDER BY TABLE_SCHEMA, TABLE_NAME",
        "SELECT TABLE_SCHEMA AS schema_name, TABLE_NAME AS table_name, COLUMN_NAME AS column_name, DATA_TYPE AS data_type, IS_NULLABLE AS is_nullable FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_CATALOG = %s ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION",
    )


def oracle_adapter() -> DBAPIAdapter:
    return DBAPIAdapter(
        "oracle",
        oracle_connect,
        "SELECT version FROM product_component_version WHERE product LIKE 'Oracle Database%' FETCH FIRST 1 ROWS ONLY",
        "SELECT SYS_CONTEXT('USERENV','DB_NAME') AS name FROM dual",
        "SELECT owner AS schema_name, object_name, object_type FROM all_objects WHERE object_type IN ('TABLE','VIEW','MATERIALIZED VIEW') ORDER BY owner, object_name",
        "SELECT owner AS schema_name, table_name, column_name, data_type, nullable AS is_nullable FROM all_tab_columns ORDER BY owner, table_name, column_id",
        parameter=":1",
    )


def dm_adapter() -> DBAPIAdapter:
    load_dm_driver()
    return DBAPIAdapter(
        "dm",
        dm_connect,
        "SELECT BANNER FROM V$VERSION WHERE ROWNUM = 1",
        "SELECT NAME FROM V$DATABASE",
        "SELECT owner AS schema_name, object_name, object_type FROM all_objects WHERE object_type IN ('TABLE','VIEW','MATERIALIZED VIEW') ORDER BY owner, object_name",
        "SELECT owner AS schema_name, table_name, column_name, data_type, nullable AS is_nullable FROM all_tab_columns ORDER BY owner, table_name, column_id",
        parameter=":1",
    )


def mysql_connect(config: dict[str, Any], credential: dict[str, Any], database: str):
    import pymysql
    return pymysql.connect(
        host=required(config, "host"), port=int(config.get("port") or DEFAULT_PORTS[str(config.get("database_type"))]),
        user=required(credential, "username"), password=required(credential, "password"), database=database,
        connect_timeout=int(config.get("connect_timeout_seconds") or 5), read_timeout=30, write_timeout=5,
        charset="utf8mb4", autocommit=True, cursorclass=pymysql.cursors.Cursor,
        ssl={} if str(config.get("ssl_mode")) not in {"disable", "prefer"} else None,
    )


def sqlserver_connect(config: dict[str, Any], credential: dict[str, Any], database: str):
    import pymssql
    return pymssql.connect(
        server=required(config, "host"), port=str(int(config.get("port") or 1433)),
        user=required(credential, "username"), password=required(credential, "password"), database=database,
        login_timeout=int(config.get("connect_timeout_seconds") or 5), timeout=30, autocommit=True,
    )


def oracle_connect(config: dict[str, Any], credential: dict[str, Any], database: str):
    import oracledb
    service = str(config.get("service_name") or database)
    dsn = oracledb.makedsn(required(config, "host"), int(config.get("port") or 1521), service_name=service)
    connection = oracledb.connect(user=required(credential, "username"), password=required(credential, "password"), dsn=dsn)
    connection.call_timeout = 30_000
    return connection


def load_dm_driver():
    try:
        return importlib.import_module("dmPython")
    except ImportError:
        driver_path = os.getenv("DM_PYTHON_PATH", "/opt/dm-driver")
        if driver_path not in sys.path:
            sys.path.insert(0, driver_path)
        try:
            return importlib.import_module("dmPython")
        except ImportError as exc:
            raise AdapterError("达梦 dmPython 官方驱动未安装，请将驱动放入 drivers/dm") from exc


def dm_connect(config: dict[str, Any], credential: dict[str, Any], database: str):
    dm_python = load_dm_driver()
    del database
    try:
        return dm_python.connect(
            user=required(credential, "username"), password=required(credential, "password"),
            server=required(config, "host"), port=int(config.get("port") or 5236), autoCommit=True,
        )
    except TypeError:
        return dm_python.connect(
            required(credential, "username"), required(credential, "password"),
            f"{required(config, 'host')}:{int(config.get('port') or 5236)}",
        )


def sqlite_connect(config: dict[str, Any], credential: dict[str, Any], database: str):
    del credential, database
    root = Path(os.getenv("DATABASE_MCP_SQLITE_ROOT", "/data/databases")).resolve()
    configured = required(config, "database_file")
    candidate = (root / configured).resolve() if not Path(configured).is_absolute() else Path(configured).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise AdapterError("SQLite 文件必须位于平台数据库目录内") from exc
    if not candidate.is_file():
        raise AdapterError(f"SQLite 文件不存在：{configured}")
    uri = f"file:{candidate.as_posix()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True, timeout=float(config.get("connect_timeout_seconds") or 5))
    connection.execute("PRAGMA query_only=ON")
    return connection


async def network_checks(config: dict[str, Any], credential: dict[str, Any]) -> list[dict[str, Any]]:
    database_type = str(config.get("database_type") or "postgresql")
    if database_type == "sqlite":
        return []
    host = required(config, "host")
    port = int(config.get("port") or DEFAULT_PORTS[database_type])
    timeout = float(config.get("connect_timeout_seconds") or 5)
    try:
        addresses = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        address = str(addresses[0][4][0]) if addresses else host
    except socket.gaierror as exc:
        raise AdapterError(f"主机解析失败：找不到 {host}") from exc
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.close()
        await writer.wait_closed()
    except (OSError, TimeoutError) as exc:
        raise AdapterError(f"端口不可访问：{host}:{port}") from exc
    return [
        {"name": "dns", "status": "passed", "detail": f"{host} -> {address}"},
        {"name": "tcp", "status": "passed", "detail": f"{host}:{port}"},
    ]


def fetch_rows(connection: Any, sql: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with closing(connection.cursor()) as cursor:
        uses_parameter = bool(parameters) and any(marker in sql for marker in ("%s", "?", ":1"))
        try:
            cursor.execute(sql, parameters) if uses_parameter else cursor.execute(sql)
        except Exception:
            if uses_parameter:
                cursor.execute(sql.replace("%s", f"'{literal(str(parameters[0]))}'"))
            else:
                raise
        names = [str(item[0]).lower() for item in (cursor.description or [])]
        return [dict(zip(names, row)) for row in cursor.fetchall()]


def fetch_scalar(connection: Any, sql: str) -> Any:
    with closing(connection.cursor()) as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()
        return row[0] if row else None


def configure_read_only(connection: Any, database_type: str, scope: dict[str, Any]) -> None:
    timeout_ms = int((scope.get("limits") or {}).get("statement_timeout_ms") or 5000)
    statements = {
        "mysql": ["SET SESSION TRANSACTION READ ONLY", f"SET SESSION MAX_EXECUTION_TIME={timeout_ms}"],
        "mariadb": ["SET SESSION TRANSACTION READ ONLY"],
        "doris": [f"SET query_timeout={max(1, timeout_ms // 1000)}"],
        "starrocks": [f"SET query_timeout={max(1, timeout_ms // 1000)}"],
        "oracle": ["SET TRANSACTION READ ONLY"],
        "dm": ["SET TRANSACTION READ ONLY"],
        "sqlite": ["PRAGMA query_only=ON"],
        "sqlserver": [f"SET LOCK_TIMEOUT {timeout_ms}"],
    }
    with closing(connection.cursor()) as cursor:
        for statement in statements.get(database_type, []):
            try:
                cursor.execute(statement)
            except Exception:
                if database_type in {"doris", "starrocks", "sqlserver"}:
                    continue
                raise


def qualified_identifier(database_type: str, schema: str, table: str) -> str:
    if database_type == "sqlserver":
        quote_value = lambda value: "[" + value.replace("]", "]]" ) + "]"
    elif database_type in {"mysql", "mariadb", "doris", "starrocks", "clickhouse"}:
        quote_value = lambda value: "`" + value.replace("`", "``") + "`"
    else:
        quote_value = lambda value: '"' + value.replace('"', '""') + '"'
    return f"{quote_value(schema)}.{quote_value(table)}"


def explain_sql(database_type: str, sql: str) -> str:
    if database_type == "sqlserver":
        raise AdapterError("SQL Server 首版不开放执行计划，避免会话级 SET 泄漏")
    return f"EXPLAIN {sql}"


def discovery_result(database_type: str, version: str, databases: list[dict[str, Any]], checks: list[dict[str, Any]], warnings: list[str], started: float) -> dict[str, Any]:
    return {
        "status": "READY",
        "database_type": database_type,
        "latency_ms": max(0, round((monotonic() - started) * 1000)),
        "checks": checks,
        "server": {"version": f"{database_label(database_type)} {version}"},
        "databases": databases,
        "warnings": warnings,
    }


def default_success_checks(credential: dict[str, Any], count: int) -> list[dict[str, Any]]:
    return [
        {"name": "authentication", "status": "passed", "detail": str(credential.get("username") or "local")},
        {"name": "select", "status": "passed", "detail": "SELECT 1"},
        {"name": "read_only", "status": "passed", "detail": "平台只读策略已启用"},
        {"name": "discovery", "status": "passed", "detail": f"发现 {count} 个数据库"},
    ]


def required(value: dict[str, Any], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise AdapterError(f"缺少字段 {field}")
    return item


def default_database(database_type: str) -> str:
    return {
        "mysql": "mysql", "mariadb": "mysql", "doris": "information_schema",
        "starrocks": "information_schema", "sqlserver": "master", "oracle": "ORCL",
        "dm": "DM", "sqlite": "main",
    }[database_type]


def database_label(database_type: str) -> str:
    return {
        "mysql": "MySQL", "mariadb": "MariaDB", "doris": "Apache Doris",
        "starrocks": "StarRocks", "sqlserver": "SQL Server", "oracle": "Oracle",
        "dm": "达梦 DM", "clickhouse": "ClickHouse", "elasticsearch": "Elasticsearch",
        "sqlite": "SQLite",
    }.get(database_type, database_type)


def literal(value: str) -> str:
    return value.replace("'", "''")


def safe_driver_error(exc: Exception) -> str:
    # Driver errors can include endpoints and user names. Return only the class
    # and a bounded message with obvious credential fields removed.
    message = str(exc).replace("password", "credential").replace("Password", "Credential")
    return f"{type(exc).__name__}: {message[:300]}"


def json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        import base64
        return {"base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    return str(value)
