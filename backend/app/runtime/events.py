from __future__ import annotations

from typing import Any


TRACE_STEP_TYPES = {
    "start": "runtime",
    "plan": "plan",
    "skill_load": "skill",
    "tool_call": "mcp",
    "tool_started": "mcp",
    "tool_completed": "mcp",
    "tool_result": "mcp",
    "model_call": "model",
    "artifact": "artifact",
    "artifact_save": "artifact",
    "repository_scan": "repository",
    "code_edit": "code",
    "test_run": "test",
    "git_diff": "git",
    "end": "runtime",
}


def normalize_trace_event(raw: dict[str, Any]) -> tuple[str, str, str]:
    event_type = str(raw.get("event") or raw.get("type") or "runtime_event").lower()
    normalized = event_type.replace(".", "_")
    step_type = TRACE_STEP_TYPES.get(normalized, "runtime")
    raw_status = str(raw.get("status") or "succeeded").lower()
    status = (
        "failed"
        if raw_status in {"failed", "error"}
        else "cancelled"
        if raw_status in {"cancelled", "canceled"}
        else "running"
        if raw_status in {"running", "started", "pending"}
        else "succeeded"
    )
    return event_type, step_type, status
