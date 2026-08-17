#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PROJECT_NAME=${HERMES_COMPOSE_PROJECT_NAME:-hermes-agent-platform}
API_URL=${API_URL:-http://127.0.0.1:18088}
PI_RUNTIME_TEST_MODEL=${PI_RUNTIME_TEST_MODEL:-${MODEL_NAME:-}}
PI_REFERENCE_AGENT_ID=${PI_REFERENCE_AGENT_ID:-111111111}
PI_WRITE_HB_SKILL_ID=${PI_WRITE_HB_SKILL_ID:-write-hb}
PI_KNOWLEDGE_TOPIC=${PI_KNOWLEDGE_TOPIC:-欧盟对中国产聚酰胺纱线征收反倾销税}
RUN_SUFFIX=${PI_RUNTIME_TEST_SUFFIX:-$(date -u '+%Y%m%d%H%M%S')}
COMPOSE="docker compose -p $PROJECT_NAME -f $PROJECT_ROOT/docker-compose.yml"
TMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/hermes-pi-deployment.XXXXXX")
trap 'rm -rf "$TMP_ROOT"' EXIT HUP INT TERM

test -n "$PI_RUNTIME_TEST_MODEL" || {
  echo "PI_RUNTIME_TEST_MODEL or MODEL_NAME is required" >&2
  exit 1
}
case "$RUN_SUFFIX" in
  *[!a-z0-9]*|'')
    echo "PI_RUNTIME_TEST_SUFFIX must contain only lowercase letters and digits" >&2
    exit 1
    ;;
esac
test "${#RUN_SUFFIX}" -le 24 || {
  echo "PI_RUNTIME_TEST_SUFFIX must contain at most 24 characters" >&2
  exit 1
}

stage() {
  printf '[phase5-pi] %s\n' "$1"
}

create_agent() {
  payload=$1
  curl -fsS -X POST "$API_URL/api/agents" \
    -H 'Content-Type: application/json' \
    --data-binary "@$payload" >/dev/null
}

run_sync() {
  agent_id=$1
  payload=$2
  output=$3
  curl -fsS --max-time 600 -X POST \
    "$API_URL/api/agents/$agent_id/run?response_mode=sync" \
    -H 'Content-Type: application/json' \
    --data-binary "@$payload" >"$output"
}

stage "checking service health, official Pi package, and container isolation"
curl -fsS "$API_URL/health" >"$TMP_ROOT/health.json"
python3 - "$TMP_ROOT/health.json" <<'PY'
import json, pathlib, sys
value = json.loads(pathlib.Path(sys.argv[1]).read_text())
assert value["status"] == "ok", value
PY

PI_CONTAINER=$($COMPOSE ps -q pi-runtime)
test -n "$PI_CONTAINER"
docker inspect "$PI_CONTAINER" >"$TMP_ROOT/pi-inspect.json"
python3 - "$TMP_ROOT/pi-inspect.json" <<'PY'
import json, pathlib, sys
value = json.loads(pathlib.Path(sys.argv[1]).read_text())[0]
assert value["State"]["Health"]["Status"] == "healthy", value["State"]
assert value["HostConfig"]["ReadonlyRootfs"] is True
assert "ALL" in (value["HostConfig"].get("CapDrop") or [])
assert not (value["HostConfig"].get("PortBindings") or {})
assert not value.get("Mounts"), value.get("Mounts")
networks = set(value["NetworkSettings"]["Networks"])
assert len(networks) == 1 and next(iter(networks)).endswith("-pi-runtime"), networks
PY
$COMPOSE exec -T pi-runtime node -e \
  "import('@earendil-works/pi-agent-core').then(()=>process.exit(0)).catch(()=>process.exit(1))"
if $COMPOSE exec -T pi-runtime node -e \
  "require('node:dns').lookup('postgres', error => process.exit(error ? 0 : 1))"; then
  :
else
  echo "pi-runtime can resolve the PostgreSQL service directly" >&2
  exit 1
fi
if $COMPOSE exec -T pi-runtime node -e \
  "fetch('https://1.1.1.1', {signal: AbortSignal.timeout(3000)}).then(()=>process.exit(1)).catch(()=>process.exit(0))"; then
  :
else
  echo "pi-runtime has direct public egress" >&2
  exit 1
fi

stage "checking automatic Runtime registration and health"
curl -fsS "$API_URL/api/runtimes" >"$TMP_ROOT/runtimes.json"
PI_RUNTIME_ID=$(python3 - "$TMP_ROOT/runtimes.json" <<'PY'
import json, pathlib, sys
values = json.loads(pathlib.Path(sys.argv[1]).read_text())
pi = [item for item in values if item["type"] == "pi" and item["name"] == "Pi Runtime"]
hermes = [item for item in values if item["type"] == "hermes" and item["name"] == "Hermes Runtime"]
assert len(pi) == len(hermes) == 1, values
assert pi[0]["version"] == "0.84.2", pi[0]
print(pi[0]["id"])
PY
)
curl -fsS -X POST "$API_URL/api/runtimes/$PI_RUNTIME_ID/health" >"$TMP_ROOT/runtime-health.json"
python3 - "$TMP_ROOT/runtime-health.json" <<'PY'
import json, pathlib, sys
value = json.loads(pathlib.Path(sys.argv[1]).read_text())
assert value["status"] == "online" and value["version"] == "0.84.2", value
PY

HELLO_AGENT="pi-hello-$RUN_SUFFIX"
FILE_AGENT="pi-file-$RUN_SUFFIX"
KNOWLEDGE_AGENT="pi-write-hb-$RUN_SUFFIX"
FILESYSTEM_MCP="pi-filesystem-$RUN_SUFFIX"
DATABASE_MCP="pi-database-$RUN_SUFFIX"
FILE_NAME="phase5-pi-$RUN_SUFFIX.txt"
FILE_MARKER="PI_FILESYSTEM_EVIDENCE_$RUN_SUFFIX"
DATABASE_MARKER="PI_DATABASE_EVIDENCE_$RUN_SUFFIX"

stage "creating and running a standalone Pi Hello Agent"
python3 - "$TMP_ROOT/hello-agent.json" "$HELLO_AGENT" "$PI_RUNTIME_ID" "$PI_RUNTIME_TEST_MODEL" <<'PY'
import json, pathlib, sys
path, agent_id, runtime_id, model = sys.argv[1:]
value = {
    "id": agent_id,
    "name": "Pi Hello Agent " + agent_id.rsplit("-", 1)[-1],
    "description": "Phase 5 official Pi Runtime acceptance",
    "role": "Pi Runtime acceptance agent",
    "system_prompt": "Use the official Pi agent loop. Answer briefly in Chinese.",
    "model_config": {},
    "model": model,
    "prompt_template": "{{input}}",
    "model_adapter": "qwen",
    "runtime_type": "pi",
    "runtime_config": {"runtime_id": runtime_id},
    "status": "active",
    "response_mode": "sync",
    "input_schema": {},
    "output_schema": {},
}
pathlib.Path(path).write_text(json.dumps(value, ensure_ascii=False))
PY
create_agent "$TMP_ROOT/hello-agent.json"
printf '%s' '{"input":"请回复：Pi Runtime 真实同步执行成功。","session_id":"pi-hello-sync"}' >"$TMP_ROOT/hello-run.json"
run_sync "$HELLO_AGENT" "$TMP_ROOT/hello-run.json" "$TMP_ROOT/hello-result.json"
HELLO_EXECUTION=$(python3 - "$TMP_ROOT/hello-result.json" <<'PY'
import json, pathlib, sys
value = json.loads(pathlib.Path(sys.argv[1]).read_text())
assert value["status"] == "succeeded" and value["runtime"] == "pi", value
assert value["runtime_run_id"] == value["execution_id"], value
assert value["output"].strip(), value
print(value["execution_id"])
PY
)
curl -fsS "$API_URL/api/executions/$HELLO_EXECUTION" >"$TMP_ROOT/hello-execution.json"
curl -fsS "$API_URL/api/executions/$HELLO_EXECUTION/trace" >"$TMP_ROOT/hello-trace.json"
python3 - "$PI_RUNTIME_ID" "$TMP_ROOT/hello-execution.json" "$TMP_ROOT/hello-trace.json" <<'PY'
import json, pathlib, sys
runtime_id = sys.argv[1]
execution = json.loads(pathlib.Path(sys.argv[2]).read_text())
trace = json.loads(pathlib.Path(sys.argv[3]).read_text())
assert execution["runtime_type"] == trace["runtime_type"] == "pi"
assert execution["runtime_id"] == trace["runtime_id"] == runtime_id
assert execution["artifact_count"] >= 1
assert any(node["step_type"] == "runtime" for node in trace["nodes"])
assert any(node["step_type"] == "artifact" for node in trace["nodes"])
PY

stage "creating a File Agent and verifying a real filesystem_read MCP call"
mkdir -p "$PROJECT_ROOT/data/mcp-files"
printf '%s\n' "$FILE_MARKER" >"$PROJECT_ROOT/data/mcp-files/$FILE_NAME"
chmod 0444 "$PROJECT_ROOT/data/mcp-files/$FILE_NAME"
chown "${MCP_GATEWAY_UID:-10001}:${MCP_GATEWAY_GID:-10001}" "$PROJECT_ROOT/data/mcp-files/$FILE_NAME"
curl -fsS -X POST "$API_URL/api/mcp-servers" -H 'Content-Type: application/json' --data "{
  \"id\":\"$FILESYSTEM_MCP\",\"name\":\"Pi Filesystem $RUN_SUFFIX\",
  \"endpoint\":\"http://mcp-gateway:8090/mcp\",
  \"config\":{\"kind\":\"filesystem\",\"read_only\":true},\"permission\":\"read_only\"
}" >/dev/null
curl -fsS -X POST "$API_URL/api/mcp-servers" -H 'Content-Type: application/json' --data "{
  \"id\":\"$DATABASE_MCP\",\"name\":\"Pi Database $RUN_SUFFIX\",
  \"endpoint\":\"http://mcp-gateway:8090/mcp\",
  \"config\":{\"kind\":\"database\",\"read_only\":true},\"permission\":\"read_only\"
}" >/dev/null
python3 - "$TMP_ROOT/file-agent.json" "$FILE_AGENT" "$PI_RUNTIME_ID" "$PI_RUNTIME_TEST_MODEL" "$FILE_NAME" <<'PY'
import json, pathlib, sys
path, agent_id, runtime_id, model, filename = sys.argv[1:]
value = {
    "id": agent_id, "name": "Pi File Agent " + agent_id.rsplit("-", 1)[-1],
    "description": "Phase 5 Pi MCP acceptance", "role": "file evidence analyst",
    "system_prompt": (
        "You must call filesystem_read exactly once with path " + filename +
        ". Return the exact file content and never guess it."
    ),
    "model_config": {}, "model": model, "prompt_template": "{{input}}",
    "model_adapter": "qwen", "runtime_type": "pi",
    "runtime_config": {"runtime_id": runtime_id}, "status": "active",
    "response_mode": "sync", "input_schema": {}, "output_schema": {},
}
pathlib.Path(path).write_text(json.dumps(value, ensure_ascii=False))
PY
create_agent "$TMP_ROOT/file-agent.json"
curl -fsS -X PUT "$API_URL/api/agents/$FILE_AGENT/mcp-servers/$FILESYSTEM_MCP" >/dev/null
python3 - "$TMP_ROOT/file-run.json" "$FILE_NAME" <<'PY'
import json, pathlib, sys
pathlib.Path(sys.argv[1]).write_text(json.dumps({
    "input": "调用 filesystem_read 读取 " + sys.argv[2] + " 并原样返回内容。",
    "session_id": "pi-file-sync",
}, ensure_ascii=False))
PY
run_sync "$FILE_AGENT" "$TMP_ROOT/file-run.json" "$TMP_ROOT/file-result.json"
FILE_EXECUTION=$(python3 - "$TMP_ROOT/file-result.json" "$FILE_MARKER" <<'PY'
import json, pathlib, sys
value = json.loads(pathlib.Path(sys.argv[1]).read_text())
assert value["status"] == "succeeded" and value["runtime"] == "pi", value
assert sys.argv[2] in value["output"], value["output"]
print(value["execution_id"])
PY
)
curl -fsS "$API_URL/api/executions/$FILE_EXECUTION" >"$TMP_ROOT/file-execution.json"
python3 - "$TMP_ROOT/file-execution.json" <<'PY'
import json, pathlib, sys
value = json.loads(pathlib.Path(sys.argv[1]).read_text())
calls = value["details"].get("mcp_calls", [])
assert any(call.get("tool") == "filesystem_read" and call.get("status") == "succeeded" for call in calls), calls
assert value["artifact_count"] >= 1
PY

stage "checking write-hb runtime support and removed online-search tool configuration"
curl -fsS "$API_URL/api/skills/$PI_WRITE_HB_SKILL_ID" >"$TMP_ROOT/write-hb-skill.json"
WRITE_HB_PATH=$(python3 - "$TMP_ROOT/write-hb-skill.json" <<'PY'
import json, pathlib, sys
value = json.loads(pathlib.Path(sys.argv[1]).read_text())
assert "pi" in value["runtime_support"], value
print(value["path"])
PY
)
if $COMPOSE exec -T agent-api sh -ec \
  "grep -RniE 'TAVILY_API_KEY|SERPAPI_API_KEY|BING_SEARCH_API_KEY|GOOGLE_SEARCH_API_KEY|tool:[[:space:]]*(web_search|browser|tavily)' '/app/skills/$WRITE_HB_PATH' >/dev/null"; then
  echo "write-hb still contains executable online-search configuration" >&2
  exit 1
fi

stage "cloning the reference configuration into a separate Pi write-hb Agent"
curl -fsS "$API_URL/api/agents/$PI_REFERENCE_AGENT_ID" >"$TMP_ROOT/reference-agent.json"
python3 - "$TMP_ROOT/reference-agent.json" "$TMP_ROOT/knowledge-agent.json" \
  "$KNOWLEDGE_AGENT" "$PI_RUNTIME_ID" "$PI_RUNTIME_TEST_MODEL" "$FILE_NAME" "$DATABASE_MARKER" <<'PY'
import json, pathlib, sys
source_path, target_path, agent_id, runtime_id, model, filename, database_marker = sys.argv[1:]
source = json.loads(pathlib.Path(source_path).read_text())
value = {
    "id": agent_id,
    "name": "Pi write-hb Acceptance " + agent_id.rsplit("-", 1)[-1],
    "description": "Separate Pi Agent; the reference Hermes Agent is unchanged.",
    "agent_type": "worker",
    "role": source["role"],
    "system_prompt": source["system_prompt"] + (
        "\nBefore the final JSON, call filesystem_read with path " + filename +
        " and call database_query with SQL SELECT '" + database_marker +
        "' AS evidence_marker. These two markers validate the tool chain only and are not topic evidence."
    ),
    "model_config": source.get("model_config", {}),
    "model": model,
    "prompt_template": source["prompt_template"],
    "model_adapter": source["model_adapter"],
    "runtime_type": "pi",
    "runtime_config": {"runtime_id": runtime_id},
    "status": "active",
    "response_mode": "sync",
    "input_schema": source.get("input_schema", {}),
    "output_schema": source.get("output_schema", {}),
}
pathlib.Path(target_path).write_text(json.dumps(value, ensure_ascii=False))
PY
create_agent "$TMP_ROOT/knowledge-agent.json"
curl -fsS -X PUT "$API_URL/api/agents/$KNOWLEDGE_AGENT/skills/$PI_WRITE_HB_SKILL_ID" >/dev/null
curl -fsS -X PUT "$API_URL/api/agents/$KNOWLEDGE_AGENT/mcp-servers/$FILESYSTEM_MCP" >/dev/null
curl -fsS -X PUT "$API_URL/api/agents/$KNOWLEDGE_AGENT/mcp-servers/$DATABASE_MCP" >/dev/null
python3 - "$TMP_ROOT/knowledge-run.json" "$PI_KNOWLEDGE_TOPIC" <<'PY'
import json, pathlib, sys
topic = sys.argv[2]
pathlib.Path(sys.argv[1]).write_text(json.dumps({
    "input": topic,
    "session_id": "pi-write-hb-sync",
    "parameters": {"topic": topic},
}, ensure_ascii=False))
PY
run_sync "$KNOWLEDGE_AGENT" "$TMP_ROOT/knowledge-run.json" "$TMP_ROOT/knowledge-result.json"
KNOWLEDGE_EXECUTION=$(python3 - "$TMP_ROOT/knowledge-result.json" <<'PY'
import json, pathlib, sys
value = json.loads(pathlib.Path(sys.argv[1]).read_text())
assert value["status"] == "succeeded" and value["runtime"] == "pi", value
structured = json.loads(value["output"])
assert isinstance(structured, dict), structured
assert structured.get("status") in {"completed", "blocked"}, structured
print(value["execution_id"])
PY
)
curl -fsS "$API_URL/api/executions/$KNOWLEDGE_EXECUTION" >"$TMP_ROOT/knowledge-execution.json"
python3 - "$TMP_ROOT/knowledge-execution.json" "$TMP_ROOT/knowledge-result.json" <<'PY'
import json, pathlib, sys
execution = json.loads(pathlib.Path(sys.argv[1]).read_text())
result = json.loads(pathlib.Path(sys.argv[2]).read_text())
calls = execution["details"].get("mcp_calls", [])
tools = {call.get("tool") for call in calls if call.get("status") == "succeeded"}
assert {"filesystem_read", "database_query"}.issubset(tools), calls
recall = execution["details"].get("source_recall", {})
assert recall.get("enabled") is True, recall
structured = json.loads(result["output"])
diagnostics = json.dumps(recall.get("diagnostics", {}), ensure_ascii=False)
if "embedding retrieval unavailable" in diagnostics:
    gaps = json.dumps(structured.get("information_gaps", []), ensure_ascii=False)
    assert "embedding" in gaps.lower() or "向量" in gaps, structured
if structured.get("status") == "completed":
    assert recall.get("source_count", 0) > 0, recall
PY

stage "verifying native SSE token streaming"
curl -fsS -N --max-time 600 -X POST \
  "$API_URL/api/agents/$HELLO_AGENT/run?response_mode=stream" \
  -H 'Accept: text/event-stream' -H 'Content-Type: application/json' \
  --data '{"input":"请用中文流式输出三句 Pi Runtime 验收结论。","session_id":"pi-hello-stream"}' \
  >"$TMP_ROOT/stream.txt"
python3 - "$TMP_ROOT/stream.txt" <<'PY'
import pathlib, sys
value = pathlib.Path(sys.argv[1]).read_text()
assert "event: start" in value
assert value.count("event: token") >= 2, value
assert "event: end" in value and '"status":"success"' in value, value
PY

stage "stopping a running queued task and checking unified cancellation state"
curl -fsS -X POST "$API_URL/api/agents/$HELLO_AGENT/tasks" \
  -H 'Content-Type: application/json' \
  --data '{"input":"请撰写一万字的运行时架构分析，在完成前不要提前结束。","session_id":"pi-stop-task","priority":9}' \
  >"$TMP_ROOT/stop-task.json"
STOP_TASK=$(python3 - "$TMP_ROOT/stop-task.json" <<'PY'
import json, pathlib, sys
print(json.loads(pathlib.Path(sys.argv[1]).read_text())["id"])
PY
)
STOP_EXECUTION=$(python3 - "$TMP_ROOT/stop-task.json" <<'PY'
import json, pathlib, sys
print(json.loads(pathlib.Path(sys.argv[1]).read_text())["execution_id"])
PY
)
STOP_SESSION=$(python3 - "$TMP_ROOT/stop-task.json" <<'PY'
import json, pathlib, sys
print(json.loads(pathlib.Path(sys.argv[1]).read_text())["session_id"])
PY
)
running=0
for _ in $(seq 1 120); do
  curl -fsS "$API_URL/api/tasks/$STOP_TASK" >"$TMP_ROOT/stop-task-current.json"
  state=$(python3 - "$TMP_ROOT/stop-task-current.json" <<'PY'
import json, pathlib, sys
print(json.loads(pathlib.Path(sys.argv[1]).read_text())["status"])
PY
)
  if [ "$state" = "running" ]; then running=1; break; fi
  case "$state" in succeeded|failed|cancelled) break ;; esac
  sleep 0.25
done
test "$running" = "1" || {
  echo "Pi stop task did not remain running long enough for cancellation" >&2
  exit 1
}
curl -fsS -X POST "$API_URL/api/executions/$STOP_EXECUTION/stop" >"$TMP_ROOT/stop-result.json"
for _ in $(seq 1 80); do
  curl -fsS "$API_URL/api/tasks/$STOP_TASK" >"$TMP_ROOT/stop-task-final.json"
  state=$(python3 - "$TMP_ROOT/stop-task-final.json" <<'PY'
import json, pathlib, sys
print(json.loads(pathlib.Path(sys.argv[1]).read_text())["status"])
PY
)
  [ "$state" = "cancelled" ] && break
  sleep 0.25
done
curl -fsS "$API_URL/api/executions/$STOP_EXECUTION" >"$TMP_ROOT/stop-execution.json"
curl -fsS "$API_URL/api/executions/$STOP_EXECUTION/trace" >"$TMP_ROOT/stop-trace.json"
curl -fsS "$API_URL/api/sessions/$STOP_SESSION" >"$TMP_ROOT/stop-session.json"
python3 - "$TMP_ROOT/stop-task-final.json" "$TMP_ROOT/stop-execution.json" \
  "$TMP_ROOT/stop-trace.json" "$TMP_ROOT/stop-session.json" <<'PY'
import json, pathlib, sys
task, execution, trace, session = [json.loads(pathlib.Path(path).read_text()) for path in sys.argv[1:]]
assert task["status"] == execution["status"] == trace["status"] == session["status"] == "cancelled"
assert all(node["status"] != "running" for node in trace["nodes"]), trace["nodes"]
assert any(node["status"] == "cancelled" for node in trace["nodes"]), trace["nodes"]
PY

stage "checking logs for secret leakage without printing secret values"
for secret_name in PI_RUNTIME_API_KEY MCP_GATEWAY_SIGNING_KEY MODEL_GATEWAY_API_KEY; do
  case "$secret_name" in
    PI_RUNTIME_API_KEY) secret_value=${PI_RUNTIME_API_KEY:-} ;;
    MCP_GATEWAY_SIGNING_KEY) secret_value=${MCP_GATEWAY_SIGNING_KEY:-} ;;
    MODEL_GATEWAY_API_KEY) secret_value=${MODEL_GATEWAY_API_KEY:-} ;;
  esac
  test -z "$secret_value" && continue
  if $COMPOSE logs --no-color --since=30m pi-runtime agent-api mcp-gateway model-gateway | \
    grep -F "$secret_value" >/dev/null; then
    echo "$secret_name was found in service logs" >&2
    exit 1
  fi
done

stage "Phase 5 official Pi Runtime deployment acceptance passed"
printf 'Hello Agent: %s execution=%s\n' "$HELLO_AGENT" "$HELLO_EXECUTION"
printf 'File Agent: %s execution=%s\n' "$FILE_AGENT" "$FILE_EXECUTION"
printf 'Knowledge Agent: %s execution=%s\n' "$KNOWLEDGE_AGENT" "$KNOWLEDGE_EXECUTION"
printf 'Cancelled task: %s execution=%s\n' "$STOP_TASK" "$STOP_EXECUTION"
