from __future__ import annotations

import copy
import re
from typing import Any


class ParameterPolicyError(ValueError):
    pass


PROTECTED_FIELDS = {
    "endpoint",
    "credential_ref",
    "connector_instance_id",
    "implementation_id",
    "resource_scope",
    "access_token",
    "api_key",
}


def apply_parameter_policy(
    arguments: dict[str, Any],
    policy: dict[str, Any] | None,
    scope: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ParameterPolicyError("arguments must be an object")
    value = copy.deepcopy(arguments)
    forbidden = set(PROTECTED_FIELDS)
    configured_forbidden = (policy or {}).get("forbidden_fields")
    if isinstance(configured_forbidden, list):
        forbidden.update(str(item) for item in configured_forbidden)
    present = sorted(_protected_paths(value, {field.lower() for field in forbidden}))
    if present:
        raise ParameterPolicyError(f"forbidden parameters: {', '.join(present)}")

    required = (policy or {}).get("required_fields")
    if isinstance(required, list):
        missing = sorted(str(field) for field in required if str(field) not in value)
        if missing:
            raise ParameterPolicyError(f"missing required parameters: {', '.join(missing)}")
    allowed_values = (policy or {}).get("allowed_values")
    if isinstance(allowed_values, dict):
        for field, choices in allowed_values.items():
            if field in value and isinstance(choices, list) and value[field] not in choices:
                raise ParameterPolicyError(f"parameter {field} is not an allowed value")
    for key, compare in (("minimum", lambda a, b: a >= b), ("maximum", lambda a, b: a <= b)):
        rules = (policy or {}).get(key)
        if isinstance(rules, dict):
            for field, limit in rules.items():
                if field in value and isinstance(value[field], (int, float)) and not isinstance(value[field], bool):
                    if not compare(value[field], limit):
                        raise ParameterPolicyError(f"parameter {field} violates {key}")
    max_length = (policy or {}).get("max_length")
    if isinstance(max_length, dict):
        for field, limit in max_length.items():
            if field in value and hasattr(value[field], "__len__") and len(value[field]) > int(limit):
                raise ParameterPolicyError(f"parameter {field} exceeds max_length")
    regex = (policy or {}).get("regex")
    if isinstance(regex, dict):
        for field, pattern in regex.items():
            if field in value and (not isinstance(value[field], str) or re.fullmatch(str(pattern), value[field]) is None):
                raise ParameterPolicyError(f"parameter {field} does not match policy")
    fixed = (policy or {}).get("fixed")
    if isinstance(fixed, dict):
        value.update(copy.deepcopy(fixed))
    injected = (policy or {}).get("injected_fields")
    if isinstance(injected, dict):
        value.update(copy.deepcopy(injected))
    if scope:
        value["resource_scope"] = copy.deepcopy(scope)
    return value


def _protected_paths(value: Any, forbidden: set[str], prefix: str = "") -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).lower() in forbidden:
                found.add(path)
            found.update(_protected_paths(item, forbidden, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.update(_protected_paths(item, forbidden, f"{prefix}[{index}]"))
    return found
