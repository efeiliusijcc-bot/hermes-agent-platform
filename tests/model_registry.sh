#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PROJECT_NAME=${HERMES_COMPOSE_PROJECT_NAME:-hermes-agent-platform}
COMPOSE="docker compose -p $PROJECT_NAME -f $PROJECT_ROOT/docker-compose.yml"

$COMPOSE exec -T agent-api python - <<'PY'
import json
import os
import uuid
import urllib.error
import urllib.request


API = "http://127.0.0.1:8000"
MANAGEMENT_KEY = os.environ["MODEL_MANAGEMENT_API_KEY"]
created_id = f"model-registry-smoke-{uuid.uuid4().hex[:8]}"
agent_id = f"model-registry-agent-{uuid.uuid4().hex[:8]}"
original_default = None
created = False
created_agent = False


def request(method, path, payload=None, key=MANAGEMENT_KEY):
    headers = {"Content-Type": "application/json"}
    if key is not None:
        headers["X-Model-Management-Key"] = key
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    value = urllib.request.Request(f"{API}{path}", data=body, headers=headers, method=method)
    with urllib.request.urlopen(value, timeout=240) as response:
        content = response.read()
        return response.status, json.loads(content) if content else None


try:
    _, models = request("GET", "/api/models", key=None)
    assert models, "model registry is empty"
    serialized = json.dumps(models)
    assert "api_key_ciphertext" not in serialized
    assert '"api_key"' not in serialized
    original_default = next((item for item in models if item["is_default"]), models[0])

    try:
        request("POST", f"/api/models/{original_default['id']}/test", key="wrong-key")
        raise AssertionError("wrong management key was accepted")
    except urllib.error.HTTPError as exc:
        assert exc.code == 401, exc.code

    payload = {
        "id": created_id,
        "display_name": "模型注册表验收",
        "provider": original_default["provider"],
        "adapter": original_default["adapter"],
        "base_url": os.environ["MODEL_ENDPOINT"],
        "upstream_model": os.environ["MODEL_NAME"],
        "api_key": os.environ.get("MODEL_API_KEY") or None,
        "is_enabled": True,
        "is_default": False,
        "timeout_seconds": 180,
        "max_retries": 1,
    }
    status, created_model = request("POST", "/api/models", payload)
    assert status == 201 and created_model["id"] == created_id
    assert created_model["api_key_configured"] == bool(os.environ.get("MODEL_API_KEY"))
    created = True

    _, updated = request(
        "PATCH",
        f"/api/models/{created_id}",
        {"display_name": "模型注册表验收-已更新", "max_retries": 2},
    )
    assert updated["display_name"].endswith("已更新") and updated["max_retries"] == 2

    _, connectivity = request("POST", f"/api/models/{created_id}/test")
    assert connectivity["status"] == "online", connectivity

    status, agent = request("POST", "/api/agents", {
        "id": agent_id,
        "name": "模型注册表验收 Agent",
        "description": "临时验收 Agent",
        "role": "模型路由验收",
        "system_prompt": "Reply with OK only.",
        "model": created_id,
        "model_adapter": original_default["adapter"],
        "runtime_type": "pi",
        "runtime_config": {},
        "model_config": {"temperature": 0},
        "status": "active",
        "response_mode": "sync",
        "input_schema": {},
        "output_schema": {},
    })
    assert status == 201 and agent["model"] == created_id
    created_agent = True
    _, execution = request(
        "POST",
        f"/api/agents/{agent_id}/run?response_mode=sync",
        {"input": "Reply with OK only.", "session_id": "model-registry-smoke"},
    )
    assert execution["status"] == "succeeded" and execution["runtime"] == "pi"

    _, defaulted = request("POST", f"/api/models/{created_id}/default")
    assert defaulted["is_default"] is True
    _, restored = request("POST", f"/api/models/{original_default['id']}/default")
    assert restored["is_default"] is True
finally:
    if original_default is not None:
        try:
            request("POST", f"/api/models/{original_default['id']}/default")
        except Exception:
            pass
    if created_agent:
        try:
            request("DELETE", f"/api/agents/{agent_id}")
        except Exception:
            pass
    if created:
        try:
            request("DELETE", f"/api/models/{created_id}")
        except Exception:
            pass

_, final_models = request("GET", "/api/models", key=None)
assert all(item["id"] != created_id for item in final_models)
assert sum(1 for item in final_models if item["is_default"]) == 1
print("Model registry CRUD, auth, encryption boundary, connectivity, gateway routing, and cleanup passed")
PY
