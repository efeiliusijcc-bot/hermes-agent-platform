#!/usr/bin/env sh
set -eu

API_URL=${API_URL:-http://127.0.0.1:8080}
PI_RUNTIME_TEST_ENDPOINT=${PI_RUNTIME_TEST_ENDPOINT:?PI_RUNTIME_TEST_ENDPOINT is required}
PI_RUNTIME_TEST_VERSION=${PI_RUNTIME_TEST_VERSION:-unknown}
PI_RUNTIME_TEST_MODEL=${PI_RUNTIME_TEST_MODEL:-local-model}
RUN_SUFFIX=${PI_RUNTIME_TEST_SUFFIX:-$$}
AGENT_ID="pi-adapter-test-$RUN_SUFFIX"
RUNTIME_NAME="Pi Runtime Acceptance $RUN_SUFFIX"
TMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/hermes-pi-runtime.XXXXXX")
trap 'rm -rf "$TMP_ROOT"' EXIT HUP INT TERM

stage() {
  printf '[pi-runtime] %s\n' "$1"
}

json_id() {
  python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])'
}

stage "checking control-plane health"
curl -fsS "$API_URL/health" |
  python3 -c 'import json,sys; assert json.load(sys.stdin)["status"] == "ok"'

stage "registering external Pi Runtime"
RUNTIME_ID=$(curl -fsS -X POST "$API_URL/api/runtimes" \
  -H 'Content-Type: application/json' --data "{
    \"name\":\"$RUNTIME_NAME\",\"type\":\"pi\",\"version\":\"$PI_RUNTIME_TEST_VERSION\",
    \"endpoint\":\"$PI_RUNTIME_TEST_ENDPOINT\",\"config\":{},\"status\":\"unknown\"
  }" | json_id)

stage "checking Pi Runtime health through Agent API"
curl -fsS -X POST "$API_URL/api/runtimes/$RUNTIME_ID/health" |
  python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["status"] == "online", v'

stage "creating Pi Agent bound to Runtime registry"
curl -fsS -X POST "$API_URL/api/agents" -H 'Content-Type: application/json' --data "{
  \"id\":\"$AGENT_ID\",\"name\":\"Pi Adapter Acceptance\",\"description\":\"Pi Runtime contract test\",
  \"role\":\"knowledge analyst\",\"system_prompt\":\"Return a concise verified result.\",
  \"model\":\"$PI_RUNTIME_TEST_MODEL\",\"model_adapter\":\"qwen\",\"runtime_type\":\"pi\",
  \"runtime_config\":{\"runtime_id\":\"$RUNTIME_ID\"},\"status\":\"active\",\"response_mode\":\"sync\"
}" >/dev/null

stage "running synchronous Pi execution"
curl -fsS -X POST "$API_URL/api/agents/$AGENT_ID/run?response_mode=sync" \
  -H 'Content-Type: application/json' \
  --data '{"input":"Generate a concise project risk report.","session_id":"pi-sync"}' \
  > "$TMP_ROOT/sync.json"
EXECUTION_ID=$(python3 - "$TMP_ROOT/sync.json" <<'PY'
import json, pathlib, sys
value = json.loads(pathlib.Path(sys.argv[1]).read_text())
assert value["status"] == "succeeded", value
assert value["runtime"] == "pi", value
assert value["runtime_run_id"], value
assert value["output"], value
print(value["execution_id"])
PY
)

stage "checking Execution, Trace, Session, and Artifact provenance"
curl -fsS "$API_URL/api/executions/$EXECUTION_ID" > "$TMP_ROOT/execution.json"
curl -fsS "$API_URL/api/executions/$EXECUTION_ID/trace" > "$TMP_ROOT/trace.json"
python3 - "$RUNTIME_ID" "$TMP_ROOT/execution.json" "$TMP_ROOT/trace.json" <<'PY'
import json, pathlib, sys
runtime_id = sys.argv[1]
execution = json.loads(pathlib.Path(sys.argv[2]).read_text())
trace = json.loads(pathlib.Path(sys.argv[3]).read_text())
assert execution["runtime_type"] == "pi"
assert execution["runtime_id"] == runtime_id
assert execution["artifact_count"] >= 1
assert execution["memory_session_id"] == "pi-sync"
assert trace["runtime_type"] == "pi"
assert trace["runtime_id"] == runtime_id
assert any(node["step_type"] == "runtime" for node in trace["nodes"])
assert any(node["step_type"] == "artifact" for node in trace["nodes"])
PY

stage "running Pi SSE execution"
curl -fsS -N -X POST "$API_URL/api/agents/$AGENT_ID/run?response_mode=stream" \
  -H 'Accept: text/event-stream' -H 'Content-Type: application/json' \
  --data '{"input":"Stream a one paragraph risk summary.","session_id":"pi-stream"}' \
  > "$TMP_ROOT/stream.txt"
python3 - "$TMP_ROOT/stream.txt" <<'PY'
import pathlib, sys
value = pathlib.Path(sys.argv[1]).read_text()
assert "event: start" in value
assert "event: token" in value
assert "event: end" in value
assert '"status":"success"' in value
PY

stage "Pi Runtime Adapter acceptance passed"
