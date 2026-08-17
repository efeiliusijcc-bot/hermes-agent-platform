from __future__ import annotations

from typing import Any


RUNTIME_TYPES = ("hermes", "pi", "deepseek")
WORKSPACE_TYPES = ("document", "repository")
# Only capabilities actually enforced by the platform MCP Gateway belong here.
# DeepSeek's bundled bash/git behavior is a Runtime-local capability and must
# not be presented as an audited platform MCP capability.
CAPABILITY_NAMES = ("filesystem", "database")
ARTIFACT_TYPES = (
    "text",
    "json",
    "markdown",
    "pdf",
    "xlsx",
    "code_patch",
    "git_diff",
    "test_report",
)


def default_capability_profile(runtime_type: str) -> dict[str, Any]:
    if runtime_type == "deepseek":
        return {
            "workspace_type": "repository",
            "required_tools": [],
            "artifact_types": ["code_patch", "git_diff", "test_report"],
        }
    return {
        "workspace_type": "document",
        "required_tools": [],
        "artifact_types": ["text", "json", "markdown", "pdf", "xlsx"],
    }


def normalize_capability_profile(
    value: dict[str, Any] | None,
    *,
    runtime_type: str,
) -> dict[str, Any]:
    if runtime_type not in RUNTIME_TYPES:
        raise ValueError(f"unsupported Runtime type: {runtime_type}")
    source = value or {}
    if not isinstance(source, dict):
        raise ValueError("capability_profile must be an object")
    unknown = sorted(set(source) - {"workspace_type", "required_tools", "artifact_types"})
    if unknown:
        raise ValueError(f"capability_profile contains unsupported fields: {', '.join(unknown)}")
    defaults = default_capability_profile(runtime_type)
    workspace_type = source.get("workspace_type", defaults["workspace_type"])
    if workspace_type not in WORKSPACE_TYPES:
        raise ValueError("capability_profile.workspace_type must be document or repository")
    if runtime_type == "deepseek" and workspace_type != "repository":
        raise ValueError("DeepSeek Runtime requires a repository workspace")
    required_tools = _string_list(source.get("required_tools", defaults["required_tools"]), "required_tools")
    invalid_tools = sorted(set(required_tools) - set(CAPABILITY_NAMES))
    if invalid_tools:
        raise ValueError(f"capability_profile contains unsupported tools: {', '.join(invalid_tools)}")
    artifact_types = _string_list(
        source.get("artifact_types", defaults["artifact_types"]),
        "artifact_types",
    )
    invalid_artifacts = sorted(set(artifact_types) - set(ARTIFACT_TYPES))
    if invalid_artifacts:
        raise ValueError(
            f"capability_profile contains unsupported artifact types: {', '.join(invalid_artifacts)}"
        )
    return {
        "workspace_type": workspace_type,
        "required_tools": list(dict.fromkeys(required_tools)),
        "artifact_types": list(dict.fromkeys(artifact_types)),
    }


def validate_required_tools(
    profile: dict[str, Any],
    available_tools: set[str] | tuple[str, ...] | list[str],
) -> None:
    required = set(profile.get("required_tools") or [])
    missing = sorted(required - set(available_tools))
    if missing:
        raise ValueError(f"Runtime capabilities are unavailable: {', '.join(missing)}")


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"capability_profile.{field} must be a string array")
    return [item.strip().lower() for item in value if item.strip()]
