#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
API_URL=${API_URL:-http://${AGENT_API_TEST_HOST:-127.0.0.1}:${AGENT_V1_API_PORT:-39288}}
UI_URL=${UI_URL:-http://${FRONTEND_TEST_HOST:-127.0.0.1}:${AGENT_V1_FRONTEND_PORT:-39289}}
PROJECT_NAME=${HERMES_COMPOSE_PROJECT_NAME:-hermes-agent-v1-verify}
COMPOSE_FILES=${HERMES_COMPOSE_FILES:-"-f $PROJECT_ROOT/docker-compose.yml -f $PROJECT_ROOT/docker-compose.agent-v1.verify.yml"}
COMPOSE="docker compose -p $PROJECT_NAME $COMPOSE_FILES"
AGENT_ID=${AGENT_V1_TEST_AGENT_ID:-agent-v1-lifecycle}
TMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/hermes-agent-v1.XXXXXX")
RESPONSE_FILE="$TMP_ROOT/response.json"

stage() { printf '[agent-v1] %s\n' "$1"; }

cleanup() {
  curl -sS -o /dev/null -X DELETE "$API_URL/api/agents/$AGENT_ID" || true
  rm -rf "$TMP_ROOT"
}
trap cleanup EXIT HUP INT TERM

wait_execution() {
  execution_id=$1
  attempt=0
  while [ "$attempt" -lt 60 ]; do
    value=$(curl -fsS "$API_URL/api/executions/$execution_id")
    current=$(printf '%s' "$value" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')
    if [ "$current" = "succeeded" ]; then
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
  return 1
}

stage "checking isolated services, migration head, and frontend"
curl -fsS "$API_URL/health" | python3 -c 'import json,sys; assert json.load(sys.stdin)["status"]=="ok"'
$COMPOSE exec -T agent-api alembic current | grep -q '0010_agent_version_lifecycle (head)'
curl -fsS "$UI_URL/agents/$AGENT_ID" | grep -q '<div id="app"></div>'

stage "verifying the real 0009 to 0010 data migration"
$COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
  -c 'DROP DATABASE IF EXISTS hermes_agent_v1_probe' \
  -c 'CREATE DATABASE hermes_agent_v1_probe' >/dev/null
$COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d hermes_agent_v1_probe -v ON_ERROR_STOP=1 \
  -c 'CREATE EXTENSION IF NOT EXISTS vector' >/dev/null
$COMPOSE run --rm --no-deps --entrypoint alembic -e POSTGRES_DB=hermes_agent_v1_probe agent-api upgrade 0009_execution_history >/dev/null
$COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d hermes_agent_v1_probe -v ON_ERROR_STOP=1 -c "
  INSERT INTO agents (id,name,role,system_prompt,model_config,status,input_schema,output_schema,response_mode,model,prompt_template,model_adapter,api_enabled)
  VALUES ('agent-v1-migration','Migration Agent','probe','probe','{}','published','{}','{}','sync','probe-model','{{input}}','qwen',true);
  INSERT INTO agent_versions (id,agent_id,version,snapshot,status,published_at)
  VALUES
    ('00000000-0000-0000-0000-000000000101','agent-v1-migration','v1','{}','published',now()-interval '2 minutes'),
    ('00000000-0000-0000-0000-000000000102','agent-v1-migration','v2','{}','snapshot',NULL),
    ('00000000-0000-0000-0000-000000000103','agent-v1-migration','v0','{}','superseded',now()-interval '3 minutes');
  INSERT INTO execution_logs (id,agent_id,status,input,input_json,details,response_mode,started_at,finished_at)
  VALUES ('00000000-0000-0000-0000-000000000104','agent-v1-migration','succeeded','probe','{}','{}','sync',now()-interval '1 minute',now());
" >/dev/null
$COMPOSE run --rm --no-deps --entrypoint alembic -e POSTGRES_DB=hermes_agent_v1_probe agent-api upgrade head >/dev/null
$COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d hermes_agent_v1_probe -v ON_ERROR_STOP=1 -c \
  "SELECT agent.status || '|' || current.version || '|' || development.status || '|' || deprecated.status FROM agents agent JOIN agent_versions current ON current.id=agent.current_version_id JOIN agent_versions development ON development.version='v2' AND development.agent_id=agent.id JOIN agent_versions deprecated ON deprecated.version='v0' AND deprecated.agent_id=agent.id WHERE agent.id='agent-v1-migration'" | grep -qx 'active|v1|development|deprecated'
$COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d hermes_agent_v1_probe -v ON_ERROR_STOP=1 -c \
  "SELECT agent_version_id FROM execution_logs WHERE id='00000000-0000-0000-0000-000000000104'" | grep -qx '00000000-0000-0000-0000-000000000101'
$COMPOSE exec -T postgres psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -c 'DROP DATABASE hermes_agent_v1_probe' >/dev/null

stage "creating an Active Agent and Development Version"
curl -fsS -X DELETE "$API_URL/api/agents/$AGENT_ID" >/dev/null 2>&1 || true
curl -fsS -X POST "$API_URL/api/agents" -H 'Content-Type: application/json' --data "{
  \"id\":\"$AGENT_ID\",\"name\":\"Agent v1 Lifecycle\",\"description\":\"isolated lifecycle validation\",
  \"role\":\"version tester\",\"system_prompt\":\"Return AGENT_VERSION_OK.\",
  \"model\":\"agent-v1-contract-model\",\"model_adapter\":\"qwen\",\"prompt_template\":\"{{input}}\",
  \"model_config\":{},\"status\":\"active\",\"response_mode\":\"sync\",
  \"input_schema\":{},\"output_schema\":{}
}" | python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["status"]=="active" and v["current_version_id"] is None'

v1=$(curl -fsS -X POST "$API_URL/api/agents/$AGENT_ID/versions" -H 'Content-Type: application/json' --data '{"version":"v1","notes":"first release","created_by":"isolated-test"}')
V1_ID=$(printf '%s' "$v1" | python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["status"]=="development" and v["created_by"]=="isolated-test"; print(v["id"])')
curl -fsS -X PATCH "$API_URL/api/agents/$AGENT_ID/versions/v1/status" -H 'Content-Type: application/json' --data '{"status":"testing"}' >/dev/null

stage "running the independent Testing Version"
tested=$(curl -fsS -X POST "$API_URL/api/agents/$AGENT_ID/versions/v1/run" -H 'Content-Type: application/json' --data '{"input":"version test","session_id":"version-v1"}')
TEST_EXECUTION_ID=$(printf '%s' "$tested" | python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["status"]=="succeeded"; print(v["execution_id"])')
curl -fsS "$API_URL/api/executions/$TEST_EXECUTION_ID" > "$TMP_ROOT/test-execution.json"
python3 -c 'import json,sys; value=json.load(open(sys.argv[2])); assert value["agent_version_id"]==sys.argv[1] and value["agent_version"]=="v1"' "$V1_ID" "$TMP_ROOT/test-execution.json"

stage "publishing the Release Candidate"
curl -fsS -X PATCH "$API_URL/api/agents/$AGENT_ID/versions/v1/status" -H 'Content-Type: application/json' --data '{"status":"release_candidate"}' >/dev/null
curl -fsS -X POST "$API_URL/api/agents/$AGENT_ID/versions/v1/publish" | python3 -c 'import json,sys; assert json.load(sys.stdin)["status"]=="published"'
curl -fsS "$API_URL/api/agents/$AGENT_ID" > "$TMP_ROOT/agent-after-v1.json"
python3 -c 'import json,sys; value=json.load(open(sys.argv[2])); assert value["status"]=="active" and value["api_enabled"] is True; assert value["current_version_id"]==sys.argv[1]' "$V1_ID" "$TMP_ROOT/agent-after-v1.json"

stage "publishing v2 and deprecating v1"
curl -fsS -X POST "$API_URL/api/agents/$AGENT_ID/versions" -H 'Content-Type: application/json' --data '{"version":"v2","notes":"second release","created_by":"isolated-test"}' > "$TMP_ROOT/v2.json"
V2_ID=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' "$TMP_ROOT/v2.json")
curl -fsS -X PATCH "$API_URL/api/agents/$AGENT_ID/versions/v2/status" -H 'Content-Type: application/json' --data '{"status":"testing"}' >/dev/null
curl -fsS -X PATCH "$API_URL/api/agents/$AGENT_ID/versions/v2/status" -H 'Content-Type: application/json' --data '{"status":"release_candidate"}' >/dev/null
curl -fsS -X POST "$API_URL/api/agents/$AGENT_ID/versions/v2/publish" >/dev/null
curl -fsS "$API_URL/api/agents/$AGENT_ID/versions" > "$TMP_ROOT/versions-after-v2.json"
python3 -c 'import json,sys; values={item["id"]:item for item in json.load(open(sys.argv[3]))}; assert values[sys.argv[1]]["status"]=="deprecated" and values[sys.argv[1]]["deprecated_at"]; assert values[sys.argv[2]]["status"]=="published"' "$V1_ID" "$V2_ID" "$TMP_ROOT/versions-after-v2.json"

stage "checking async execution provenance and retry preservation"
queued=$(curl -fsS -X POST "$API_URL/api/agents/$AGENT_ID/tasks" -H 'Content-Type: application/json' --data '{"input":"async v2","session_id":"async-v2","priority":5}')
ASYNC_ID=$(printf '%s' "$queued" | python3 -c 'import json,sys; print(json.load(sys.stdin)["execution_id"])')
wait_execution "$ASYNC_ID" > "$TMP_ROOT/async.json"
python3 - "$V2_ID" "$TMP_ROOT/async.json" <<'PY'
import json,sys
assert json.load(open(sys.argv[2]))["agent_version_id"]==sys.argv[1]
PY
retry=$(curl -fsS -X POST "$API_URL/api/executions/$ASYNC_ID/retry" -H 'Content-Type: application/json' --data '{}')
RETRY_ID=$(printf '%s' "$retry" | python3 -c 'import json,sys; print(json.load(sys.stdin)["execution_id"])')
wait_execution "$RETRY_ID" > "$TMP_ROOT/retry.json"
python3 -c 'import json,sys; value=json.load(open(sys.argv[2])); assert value["agent_version_id"]==sys.argv[1] and value["retry_of_execution_id"]' "$V2_ID" "$TMP_ROOT/retry.json"

stage "rolling back to deprecated v1"
curl -fsS -X POST "$API_URL/api/agents/$AGENT_ID/versions/v1/rollback" > "$TMP_ROOT/rollback.json"
python3 -c 'import json,sys; value=json.load(open(sys.argv[2])); assert value["status"]=="active" and value["current_version_id"]==sys.argv[1]' "$V1_ID" "$TMP_ROOT/rollback.json"
curl -fsS "$API_URL/api/agents/$AGENT_ID/versions" > "$TMP_ROOT/versions-after-rollback.json"
python3 -c 'import json,sys; values={item["id"]:item for item in json.load(open(sys.argv[3]))}; assert values[sys.argv[1]]["status"]=="published"; assert values[sys.argv[2]]["status"]=="deprecated"' "$V1_ID" "$V2_ID" "$TMP_ROOT/versions-after-rollback.json"

stage "checking database constraints and exact execution links"
$COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c \
  "SELECT count(*) FROM agent_versions WHERE agent_id='$AGENT_ID' AND status='published'" | grep -qx 1
$COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c \
  "SELECT count(*) FROM execution_logs WHERE id='$TEST_EXECUTION_ID'::uuid AND agent_version_id='$V1_ID'::uuid" | grep -qx 1

echo "Production Agent Version lifecycle validation passed"
