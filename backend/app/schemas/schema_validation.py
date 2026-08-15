from __future__ import annotations

import copy
import json
import re
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


TYPE_MAP = {
    "string": "string",
    "number": "number",
    "integer": "integer",
    "boolean": "boolean",
    "array": "array",
    "object": "object",
}


def normalize_schema(value: dict[str, Any]) -> dict[str, Any]:
    if not value:
        return {}
    declared_type = value.get("type")
    is_schema_type = (isinstance(declared_type, str) and declared_type in TYPE_MAP) or (
        isinstance(declared_type, list)
        and bool(declared_type)
        and all(item in TYPE_MAP or item == "null" for item in declared_type)
    )
    is_full_schema = (
        is_schema_type
        or any(key in value for key in ("$schema", "$ref", "$defs", "properties", "allOf", "anyOf", "oneOf", "not"))
    )
    if is_full_schema:
        schema = copy.deepcopy(value)
    else:
        properties: dict[str, Any] = {}
        required: list[str] = []
        for key, definition in value.items():
            if isinstance(definition, str):
                properties[key] = {"type": definition}
            elif isinstance(definition, dict):
                definition = dict(definition)
                if definition.pop("required", False):
                    required.append(key)
                properties[key] = definition
            else:
                raise ValueError(f"schema field {key} must be a type string or object")
        schema = {"type": "object", "properties": properties, "additionalProperties": False}
        if required:
            schema["required"] = required
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:
        raise ValueError(f"invalid JSON Schema: {exc}") from exc
    return schema


def validate_instance(schema: dict[str, Any], value: Any, *, label: str) -> None:
    if not schema:
        return
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    if not errors:
        return
    messages: list[str] = []
    for error in errors[:10]:
        path = ".".join(str(item) for item in error.absolute_path)
        location = f" at {path}" if path else ""
        messages.append(f"{label} does not match schema{location}: {error.message}")
    if len(errors) > 10:
        messages.append(f"{len(errors) - 10} additional schema errors omitted")
    raise ValueError("; ".join(messages))


def parse_and_validate_output(schema: dict[str, Any], output: str) -> Any:
    """Parse a model's JSON response and validate it against the Agent contract."""
    if not schema:
        return output
    candidate = output.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
    try:
        result = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Agent output is not valid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}") from exc
    validate_instance(schema, result, label="Agent output")
    return result
