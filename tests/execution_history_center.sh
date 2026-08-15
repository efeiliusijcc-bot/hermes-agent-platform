#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
API_URL=${API_URL:-http://${AGENT_API_TEST_HOST:-127.0.0.1}:${EXECUTION_HISTORY_API_PORT:-39188}}
UI_URL=${UI_URL:-http://${FRONTEND_TEST_HOST:-127.0.0.1}:${EXECUTION_HISTORY_FRONTEND_PORT:-39189}}
PROJECT_NAME=${HERMES_COMPOSE_PROJECT_NAME:-hermes-agent-execution-history-verify}
COMPOSE_FILES=${HERMES_COMPOSE_FILES:-"-f $PROJECT_ROOT/docker-compose.yml -f $PROJECT_ROOT/docker-compose.execution-history.verify.yml"}
COMPOSE="docker compose -p $PROJECT_NAME $COMPOSE_FILES"
AGENT_ID=${EXECUTION_HISTORY_AGENT_ID:-execution-history-agent}
TMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/hermes-execution-history.XXXXXX")
RESPONSE_FILE="$TMP_ROOT/response.json"

stage() { printf '[execution-history] %s\n' "$1"; }

cleanup() {
  curl -sS -o /dev/null -X DELETE "$API_URL/api/agents/$AGENT_ID" || true
  rm -rf "$TMP_ROOT"
}
trap cleanup EXIT HUP INT TERM

assert_code() {
  expected=$1
  shift
  actual=$(curl -sS -o "$RESPONSE_FILE" -w '%{http_code}' "$@")
  if [ "$actual" != "$expected" ]; then
    printf '[execution-history] expected HTTP %s, received %s\n' "$expected" "$actual" >&2
    cat "$RESPONSE_FILE" >&2
    return 1
  fi
}

wait_execution() {
  execution_id=$1
  expected_status=$2
  attempt=0
  while [ "$attempt" -lt 60 ]; do
    value=$(curl -fsS "$API_URL/api/executions/$execution_id")
    current=$(printf '%s' "$value" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')
    if [ "$current" = "$expected_status" ]; then
      printf '%s' "$value"
      return 0
    fi
    if [ "$current" = "failed" ] || [ "$current" = "cancelled" ]; then
      printf '%s' "$value" >&2
      return 1
    fi
    attempt=$((attempt + 1))
    sleep 1
  done
  printf '[execution-history] execution %s did not reach %s\n' "$execution_id" "$expected_status" >&2
  return 1
}

stage "checking health, migration head, and frontend routes"
curl -fsS "$API_URL/health" | python3 -c 'import json,sys; assert json.load(sys.stdin)["status"]=="ok"'
$COMPOSE exec -T agent-api alembic current | grep -q '0009_execution_history (head)'
curl -fsS "$UI_URL/agents/$AGENT_ID/execute" | grep -q '<div id="app"></div>'
curl -fsS "$UI_URL/executions/00000000-0000-0000-0000-000000000000" | grep -q '<div id="app"></div>'

stage "verifying a real 0008 to 0009 migration with historical data"
$COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
  -c 'DROP DATABASE IF EXISTS hermes_execution_history_probe' \
  -c 'CREATE DATABASE hermes_execution_history_probe' >/dev/null
$COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d hermes_execution_history_probe -v ON_ERROR_STOP=1 \
  -c 'CREATE EXTENSION IF NOT EXISTS vector' >/dev/null
$COMPOSE run --rm --no-deps --entrypoint alembic -e POSTGRES_DB=hermes_execution_history_probe agent-api upgrade 0008_production_runtime >/dev/null
$COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d hermes_execution_history_probe -v ON_ERROR_STOP=1 -c "
  INSERT INTO agents (id,name,role,system_prompt,model_config,status,input_schema,output_schema,response_mode,model,prompt_template,model_adapter,api_enabled)
  VALUES ('history-migration-agent','History Migration Agent','probe','probe','{}','testing','{}','{}','sync','probe-model','{{input}}','qwen',false);
  INSERT INTO execution_logs (id,agent_id,status,input,output,error,details,started_at,finished_at)
  VALUES ('00000000-0000-0000-0000-000000000008','history-migration-agent','succeeded','legacy task','legacy output',NULL,'{}',now()-interval '2 seconds',now());
" >/dev/null
$COMPOSE run --rm --no-deps --entrypoint alembic -e POSTGRES_DB=hermes_execution_history_probe agent-api upgrade 0009_execution_history >/dev/null
$COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d hermes_execution_history_probe -v ON_ERROR_STOP=1 -c \
  "SELECT count(*) || '|' || (input_json->>'task') || '|' || duration_ms FROM execution_logs WHERE id='00000000-0000-0000-0000-000000000008' GROUP BY input_json,duration_ms" |
  awk -F '|' '$1==1 && $2=="legacy task" && $3>=1900 {ok=1} END {exit !ok}'
$COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d hermes_execution_history_probe -v ON_ERROR_STOP=1 -c \
  "SELECT count(*) FROM execution_steps WHERE execution_id='00000000-0000-0000-0000-000000000008'" | grep -qx 2
$COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
  -c 'DROP DATABASE hermes_execution_history_probe' >/dev/null

stage "creating schema Agent"
curl -fsS -X DELETE "$API_URL/api/agents/$AGENT_ID" >/dev/null 2>&1 || true
curl -fsS -X POST "$API_URL/api/agents" -H 'Content-Type: application/json' --data "{
  \"id\":\"$AGENT_ID\",\"name\":\"Execution History Agent\",\"description\":\"isolated contract agent\",
  \"role\":\"history tester\",\"system_prompt\":\"Return EXECUTION_HISTORY_OK.\",
  \"model\":\"execution-history-model\",\"model_adapter\":\"qwen\",\"prompt_template\":\"EXECUTION_HISTORY_OK {{topic}}\",
  \"model_config\":{},\"status\":\"testing\",\"response_mode\":\"sync\",
  \"input_schema\":{\"type\":\"object\",\"properties\":{\"topic\":{\"type\":\"string\"}},\"required\":[\"topic\"],\"additionalProperties\":false},
  \"output_schema\":{}
}" >/dev/null

stage "running sync execution with structured input and artifact"
sync=$(curl -fsS -X POST "$API_URL/api/agents/$AGENT_ID/run?response_mode=sync" -H 'Content-Type: application/json' \
  --data '{"input":"sync contract","session_id":"execution-history-sync","parameters":{"topic":"sync"},"temperature":0.2}')
SYNC_ID=$(printf '%s' "$sync" | python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["status"]=="succeeded"; print(v["execution_id"])')
curl -fsS "$API_URL/api/executions/$SYNC_ID" > "$TMP_ROOT/sync.json"
python3 - "$SYNC_ID" "$TMP_ROOT/sync.json" <<'PY'
import json,sys
execution_id,path=sys.argv[1:]
v=json.load(open(path))
assert v["id"]==execution_id and v["status"]=="succeeded" and v["response_mode"]=="sync"
assert v["input_json"]["parameters"]=={"topic":"sync"}
assert v["input_json"]["runtime_options"]=={"temperature":0.2}
names={step["step_name"] for step in v["steps"]}
assert {"Request Received","Input Schema Validate","Prompt Build","Hermes Runtime","Artifact Created"} <= names
assert len(v["artifacts"])==1 and v["artifact_count"]==1
assert isinstance(v["token_usage"],int) and v["token_usage"]>0
PY
ARTIFACT_ID=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["artifacts"][0]["id"])' "$TMP_ROOT/sync.json")
ARTIFACT_SHA=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["artifacts"][0]["sha256"])' "$TMP_ROOT/sync.json")
curl -fsS "$API_URL/api/artifacts/$ARTIFACT_ID/download" -o "$TMP_ROOT/result.txt"
test "$(sha256sum "$TMP_ROOT/result.txt" | awk '{print $1}')" = "$ARTIFACT_SHA"

stage "running stream execution"
curl -fsS -N -X POST "$API_URL/api/agents/$AGENT_ID/run?response_mode=stream" -H 'Content-Type: application/json' \
  --data '{"input":"stream contract","session_id":"execution-history-stream","parameters":{"topic":"stream"}}' > "$TMP_ROOT/stream.sse"
grep -q '^event: start' "$TMP_ROOT/stream.sse"
grep -q '^event: end' "$TMP_ROOT/stream.sse"
STREAM_ID=$(python3 - "$TMP_ROOT/stream.sse" <<'PY'
import json,sys
for line in open(sys.argv[1]):
    if line.startswith('data:'):
        value=json.loads(line[5:])
        if value.get('event')=='start': print(value['execution_id']); break
PY
)
curl -fsS "$API_URL/api/executions/$STREAM_ID" |
  python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["status"]=="succeeded" and v["response_mode"]=="stream" and len(v["steps"])>=8'

stage "running async execution and checking one Task maps to one Execution"
queued=$(curl -fsS -X POST "$API_URL/api/agents/$AGENT_ID/tasks" -H 'Content-Type: application/json' \
  --data '{"input":"async contract","session_id":"execution-history-async","parameters":{"topic":"async"},"temperature":0.1,"priority":7}')
TASK_ID=$(printf '%s' "$queued" | python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["status"]=="pending" and v["execution_id"]; print(v["id"])')
ASYNC_ID=$(printf '%s' "$queued" | python3 -c 'import json,sys; print(json.load(sys.stdin)["execution_id"])')
wait_execution "$ASYNC_ID" succeeded > "$TMP_ROOT/async.json"
python3 - "$ASYNC_ID" "$TASK_ID" "$TMP_ROOT/async.json" <<'PY'
import json,sys
execution_id,task_id,path=sys.argv[1:]
v=json.load(open(path))
assert v["id"]==execution_id and v["response_mode"]=="async"
assert v["queue_task"]["id"]==task_id and v["queue_task"]["execution_id"]==execution_id
assert v["priority"]==7 and v["input_json"]["parameters"]=={"topic":"async"}
PY

stage "checking execution list filters and search"
curl -fsS "$API_URL/api/executions?agent_id=$AGENT_ID&status=succeeded&search=contract&limit=20" |
  python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["total"]>=3 and len(v["items"])>=3; assert all(x["agent_id"]=="execution-history-agent" and x["status"]=="succeeded" for x in v["items"])'

stage "retrying completed execution with source relation"
retry_task=$(curl -fsS -X POST "$API_URL/api/executions/$SYNC_ID/retry" -H 'Content-Type: application/json' --data '{"priority":8}')
RETRY_TASK_ID=$(printf '%s' "$retry_task" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
RETRY_ID=$(printf '%s' "$retry_task" | python3 -c 'import json,sys; print(json.load(sys.stdin)["execution_id"])')
test "$RETRY_ID" != "$SYNC_ID"
wait_execution "$RETRY_ID" succeeded > "$TMP_ROOT/retry.json"
python3 - "$SYNC_ID" "$RETRY_ID" "$RETRY_TASK_ID" "$TMP_ROOT/retry.json" <<'PY'
import json,sys
source,retry,task,path=sys.argv[1:]
v=json.load(open(path))
assert v["id"]==retry and v["retry_of_execution_id"]==source
assert v["queue_task"]["id"]==task and v["response_mode"]=="async"
assert any(step["step_name"]=="Artifact Created" for step in v["steps"])
PY

stage "creating a deterministic failed execution and checking retry gate"
assert_code 422 -X POST "$API_URL/api/agents/$AGENT_ID/run?response_mode=sync" -H 'Content-Type: application/json' \
  --data '{"input":"missing required parameters","session_id":"execution-history-failed","parameters":{}}'
FAILED_ID=$(curl -fsS "$API_URL/api/executions?agent_id=$AGENT_ID&status=failed&search=missing%20required%20parameters&limit=1" |
  python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["total"]>=1; print(v["items"][0]["id"])')
curl -fsS "$API_URL/api/executions/$FAILED_ID" |
  python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["status"]=="failed" and v["error"]; assert any(s["status"]=="failed" for s in v["steps"])'

stage "checking active execution cannot be retried"
$COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "
  INSERT INTO execution_logs (id,agent_id,status,input,details,input_json,response_mode)
  VALUES ('00000000-0000-0000-0000-000000000009','$AGENT_ID','running','active retry gate','{}','{\"task\":\"active retry gate\",\"parameters\":{}}','sync')
" >/dev/null
assert_code 409 -X POST "$API_URL/api/executions/00000000-0000-0000-0000-000000000009/retry" \
  -H 'Content-Type: application/json' --data '{}'

stage "cancelling a queued Task updates its Execution lifecycle"
$COMPOSE stop agent-worker >/dev/null
cancel_task=$(curl -fsS -X POST "$API_URL/api/agents/$AGENT_ID/tasks" -H 'Content-Type: application/json' \
  --data '{"input":"cancel contract","session_id":"execution-history-cancel","parameters":{"topic":"cancel"},"priority":1}')
CANCEL_TASK_ID=$(printf '%s' "$cancel_task" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
CANCEL_EXECUTION_ID=$(printf '%s' "$cancel_task" | python3 -c 'import json,sys; print(json.load(sys.stdin)["execution_id"])')
assert_code 204 -X DELETE "$API_URL/api/tasks/$CANCEL_TASK_ID"
curl -fsS "$API_URL/api/executions/$CANCEL_EXECUTION_ID" |
  python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["status"]=="cancelled" and v["finished_at"] and v["queue_task"]["status"]=="cancelled"'
$COMPOSE start agent-worker >/dev/null

stage "checking database relationships"
$COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c \
  "SELECT count(*) FROM agent_tasks WHERE id='$TASK_ID'::uuid AND execution_id='$ASYNC_ID'::uuid" | grep -qx 1
$COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c \
  "SELECT count(*) FROM execution_artifacts WHERE execution_id='$SYNC_ID'::uuid AND artifact_id='$ARTIFACT_ID'::uuid" | grep -qx 1

echo "Execution Studio and Execution History Center validation passed"
