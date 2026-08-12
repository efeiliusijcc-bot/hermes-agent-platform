from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator, ValidationError


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
    if value.get("type") == "object" or "$schema" in value or "properties" in value:
        schema = value
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
    try:
        Draft202012Validator(schema).validate(value)
    except ValidationError as exc:
        path = ".".join(str(item) for item in exc.absolute_path)
        location = f" at {path}" if path else ""
        raise ValueError(f"{label} does not match schema{location}: {exc.message}") from exc
