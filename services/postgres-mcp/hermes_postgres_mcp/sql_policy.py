from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from pglast import ast, parse_sql


class SQLPolicyError(ValueError):
    def __str__(self) -> str:
        return f"HERMES_CAPABILITY_ERROR[INVALID_ARGUMENT]: {super().__str__()}"


AGGREGATE_FUNCTIONS = {
    "array_agg", "avg", "bit_and", "bit_or", "bool_and", "bool_or", "count",
    "every", "json_agg", "json_object_agg", "max", "min", "string_agg", "sum",
    "xmlagg", "jsonb_agg", "jsonb_object_agg",
}
DISALLOWED_NODES = tuple(
    value
    for value in (
        getattr(ast, name, None)
        for name in (
            "InsertStmt", "UpdateStmt", "DeleteStmt", "MergeStmt", "CopyStmt",
            "CallStmt", "TransactionStmt", "CreateStmt", "AlterTableStmt",
            "DropStmt", "TruncateStmt", "DoStmt", "VacuumStmt", "VariableSetStmt",
            "GrantStmt", "GrantRoleStmt", "CreateFunctionStmt",
        )
    )
    if value is not None
)


@dataclass(frozen=True)
class QueryAnalysis:
    sql: str
    relations: tuple[tuple[str | None, str], ...]
    functions: tuple[tuple[str, ...], ...]
    uses_aggregate: bool


def analyze_select(sql: str) -> QueryAnalysis:
    normalized = sql.strip()
    if normalized.endswith(";"):
        normalized = normalized[:-1].rstrip()
    if not normalized or ";" in normalized:
        raise SQLPolicyError("只允许一条 SELECT 语句")
    try:
        parsed = parse_sql(normalized)
    except Exception as exc:
        raise SQLPolicyError("SQL 语法无效") from exc
    if len(parsed) != 1 or not isinstance(parsed[0].stmt, ast.SelectStmt):
        raise SQLPolicyError("只允许 SELECT 查询")
    root = parsed[0].stmt
    if getattr(root, "intoClause", None) is not None:
        raise SQLPolicyError("禁止 SELECT INTO")
    if getattr(root, "lockingClause", None):
        raise SQLPolicyError("禁止锁定查询")
    relations: set[tuple[str | None, str]] = set()
    functions: set[tuple[str, ...]] = set()
    uses_aggregate = False
    nodes = tuple(walk(root))
    cte_names = {
        str(getattr(node, "ctename", "") or "")
        for node in nodes
        if isinstance(node, ast.CommonTableExpr)
    }
    for node in nodes:
        if isinstance(node, DISALLOWED_NODES):
            raise SQLPolicyError("查询包含写操作或管理语句")
        if isinstance(node, ast.SelectStmt):
            if getattr(node, "intoClause", None) is not None or getattr(node, "lockingClause", None):
                raise SQLPolicyError("查询包含 SELECT INTO 或锁定语句")
        if isinstance(node, ast.RangeVar):
            relation = str(node.relname or "")
            if not relation:
                raise SQLPolicyError("查询对象名称无效")
            # A CTE reference is an in-query relation, not a database object.
            # Its body is still walked, so all physical tables used by the CTE
            # remain subject to Scope validation.
            if not node.schemaname and relation in cte_names:
                continue
            relations.add((str(node.schemaname) if node.schemaname else None, relation))
        if isinstance(node, ast.FuncCall):
            name = tuple(_string_value(item) for item in node.funcname or ())
            if not name or any(not item for item in name):
                raise SQLPolicyError("函数名称无效")
            functions.add(name)
            uses_aggregate = uses_aggregate or name[-1].lower() in AGGREGATE_FUNCTIONS or bool(getattr(node, "over", None))
    return QueryAnalysis(
        sql=normalized,
        relations=tuple(sorted(relations, key=lambda item: ((item[0] or ""), item[1]))),
        functions=tuple(sorted(functions)),
        uses_aggregate=uses_aggregate,
    )


def walk(value: Any) -> Iterable[Any]:
    if value is None:
        return
    if isinstance(value, (tuple, list)):
        for item in value:
            yield from walk(item)
        return
    if value.__class__.__module__.startswith("pglast.ast"):
        yield value
        for attribute in getattr(value, "__slots__", ()):
            if attribute.startswith("_"):
                continue
            yield from walk(getattr(value, attribute, None))


def _string_value(value: Any) -> str:
    return str(getattr(value, "sval", "") or getattr(value, "str", "") or "")
