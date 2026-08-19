#!/usr/bin/env sh
set -eu

test "$#" = "1" || {
  echo "Usage: $0 /absolute/path/hermes-agent-platform-*.tar.gz" >&2
  exit 1
}

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
ARCHIVE=$1
VERIFY_ROOT=${OFFLINE_VERIFY_ROOT:-/opt/hermes-agent-platform-offline-verify}
VERIFY_PROJECT=hermes-agent-platform-offline-verify
VERIFY_PORT=28088
VERIFY_FRONTEND_PORT=28080
VERIFY_INTERNAL_NETWORK=hermes-agent-platform-offline-verify-internal
VERIFY_EDGE_NETWORK=hermes-agent-platform-offline-verify-edge
VERIFY_PI_RUNTIME_NETWORK=hermes-agent-platform-offline-verify-pi-runtime
VERIFY_DEEPSEEK_RUNTIME_NETWORK=hermes-agent-platform-offline-verify-deepseek-runtime
VERIFY_DEEPSEEK_HARNESS_NETWORK=hermes-agent-platform-offline-verify-deepseek-harness
SOURCE_COMPOSE="docker compose -p hermes-agent-platform -f $PROJECT_ROOT/docker-compose.yml"

test -f "$ARCHIVE"
test -f "$ARCHIVE.sha256"
case "$VERIFY_ROOT" in
  /opt/hermes-agent-platform-offline-verify) ;;
  *)
    echo "Unsafe offline verification root: $VERIFY_ROOT" >&2
    exit 1
    ;;
esac

expected_checksum=$(awk 'NR == 1 {print $1}' "$ARCHIVE.sha256")
actual_checksum=$(sha256sum "$ARCHIVE" | awk '{print $1}')
test "$expected_checksum" = "$actual_checksum"

source_ids_before=$($SOURCE_COMPOSE ps -q | sort)
set -a
. "$PROJECT_ROOT/.env"
set +a

if [ -f "$VERIFY_ROOT/docker-compose.yml" ]; then
  (
    cd "$VERIFY_ROOT"
    HERMES_INTERNAL_NETWORK_NAME=$VERIFY_INTERNAL_NETWORK \
    HERMES_EDGE_NETWORK_NAME=$VERIFY_EDGE_NETWORK \
    HERMES_PI_RUNTIME_NETWORK_NAME=$VERIFY_PI_RUNTIME_NETWORK \
    HERMES_DEEPSEEK_RUNTIME_NETWORK_NAME=$VERIFY_DEEPSEEK_RUNTIME_NETWORK \
    HERMES_DEEPSEEK_HARNESS_NETWORK_NAME=$VERIFY_DEEPSEEK_HARNESS_NETWORK \
      docker compose -p "$VERIFY_PROJECT" down --remove-orphans
  )
fi
rm -rf -- "$VERIFY_ROOT"
mkdir -p "$VERIFY_ROOT"
tar -xzf "$ARCHIVE" -C "$VERIFY_ROOT" --strip-components=1

OFFLINE_MODEL_ENDPOINT=$MODEL_ENDPOINT \
OFFLINE_MODEL_NAME=$MODEL_NAME \
OFFLINE_MODEL_API_KEY=$MODEL_API_KEY \
OFFLINE_MODEL_REGISTRY_ENCRYPTION_KEY=$MODEL_REGISTRY_ENCRYPTION_KEY \
OFFLINE_FRONTEND_BIND_HOST=127.0.0.1 \
  "$VERIFY_ROOT/scripts/configure-offline-env.sh"

OFFLINE_PROJECT_NAME=$VERIFY_PROJECT \
OFFLINE_AGENT_API_PORT=$VERIFY_PORT \
OFFLINE_FRONTEND_PORT=$VERIFY_FRONTEND_PORT \
OFFLINE_INTERNAL_NETWORK_NAME=$VERIFY_INTERNAL_NETWORK \
OFFLINE_EDGE_NETWORK_NAME=$VERIFY_EDGE_NETWORK \
OFFLINE_PI_RUNTIME_NETWORK_NAME=$VERIFY_PI_RUNTIME_NETWORK \
OFFLINE_DEEPSEEK_RUNTIME_NETWORK_NAME=$VERIFY_DEEPSEEK_RUNTIME_NETWORK \
OFFLINE_DEEPSEEK_HARNESS_NETWORK_NAME=$VERIFY_DEEPSEEK_HARNESS_NETWORK \
  "$VERIFY_ROOT/scripts/restore-offline-bundle.sh"

set -a
. "$VERIFY_ROOT/.env"
set +a
HERMES_COMPOSE_PROJECT_NAME=$VERIFY_PROJECT
HERMES_INTERNAL_NETWORK_NAME=$VERIFY_INTERNAL_NETWORK
HERMES_EDGE_NETWORK_NAME=$VERIFY_EDGE_NETWORK
HERMES_PI_RUNTIME_NETWORK_NAME=$VERIFY_PI_RUNTIME_NETWORK
HERMES_DEEPSEEK_RUNTIME_NETWORK_NAME=$VERIFY_DEEPSEEK_RUNTIME_NETWORK
HERMES_DEEPSEEK_HARNESS_NETWORK_NAME=$VERIFY_DEEPSEEK_HARNESS_NETWORK
AGENT_API_PORT=$VERIFY_PORT
FRONTEND_PORT=$VERIFY_FRONTEND_PORT
export HERMES_COMPOSE_PROJECT_NAME HERMES_INTERNAL_NETWORK_NAME HERMES_EDGE_NETWORK_NAME
export HERMES_PI_RUNTIME_NETWORK_NAME HERMES_DEEPSEEK_RUNTIME_NETWORK_NAME
export HERMES_DEEPSEEK_HARNESS_NETWORK_NAME AGENT_API_PORT FRONTEND_PORT
VERIFY_COMPOSE="docker compose -p $VERIFY_PROJECT -f $VERIFY_ROOT/docker-compose.yml"
VERIFY_API="http://127.0.0.1:$VERIFY_PORT"
VERIFY_FRONTEND="http://127.0.0.1:$VERIFY_FRONTEND_PORT"

AGENT_API_TEST_HOST=127.0.0.1 \
AGENT_API_PORT=$VERIFY_PORT \
HERMES_COMPOSE_PROJECT_NAME=$VERIFY_PROJECT \
  "$VERIFY_ROOT/tests/phase10_phase2_platform.sh"

test "$($VERIFY_COMPOSE ps --status running -q | wc -l | tr -d ' ')" = "16"
curl -fsS "$VERIFY_API/health" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert all(value.get(key)=="ok" for key in ("status","database","memory","knowledge")), value'
test "$(curl -fsS "$VERIFY_FRONTEND/frontend-health")" = "ok"
curl -fsS "$VERIFY_FRONTEND/health" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert all(value.get(key)=="ok" for key in ("status","database","memory","knowledge")), value'
curl -fsS "$VERIFY_FRONTEND/api/agents" | python3 -c 'import json,sys; assert isinstance(json.load(sys.stdin), list)'
curl -fsS -X POST "$VERIFY_API/api/runtimes/$(curl -fsS "$VERIFY_API/api/runtimes" | python3 -c 'import json,sys; print(next(v["id"] for v in json.load(sys.stdin) if v["type"]=="pi"))')/health" |
  python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["status"]=="online" and value["version"]=="0.84.2", value'
curl -fsS -X POST "$VERIFY_API/api/runtimes/$(curl -fsS "$VERIFY_API/api/runtimes" | python3 -c 'import json,sys; print(next(v["id"] for v in json.load(sys.stdin) if v["type"]=="deepseek"))')/health" |
  python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["status"]=="online" and value["version"]=="0.1.0-rc.6", value'
curl -fsS "$VERIFY_FRONTEND/agents/knowledge-analyst" | grep -q '<div id="app"></div>'

agent=$(curl -fsS "$VERIFY_API/api/agents/knowledge-analyst")
printf '%s' "$agent" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["role"]=="企业知识分析专家"; assert value["status"]=="active"'

test "$($VERIFY_COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT count(*) FROM knowledge_agent_ai_metrics WHERE evidence_marker = 'TITAN_DATABASE_SIGNAL_93'")" = "3"
test "$($VERIFY_COMPOSE exec -T redis sh -ec 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli EXISTS hermes:agent-memory:v1:knowledge-analyst:phase8-demo-session')" = "1"
knowledge_objects=$($VERIFY_COMPOSE run --rm --no-deps --entrypoint /bin/sh minio-init -ec '
  mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
  mc find local/knowledge/company-docs 2>/dev/null | wc -l | tr -d " "
')
test "$knowledge_objects" -ge "1"

run_result=$(curl -fsS --max-time 300 -X POST "$VERIFY_API/api/agents/knowledge-analyst/run" \
  -H 'Content-Type: application/json' \
  --data '{"session_id":"phase9-offline-session","input":"分析公司AI应用情况。"}')
printf '%s' "$run_result" | python3 -c '
import json,sys
value=json.load(sys.stdin)
output=value["output"]
assert value["status"]=="succeeded"
assert "ATLAS_KNOWLEDGE_SIGNAL_88" in output
assert "LYRA_FILE_SIGNAL_44" in output
assert "TITAN_DATABASE_SIGNAL_93" in output
'

runs=$(curl -fsS "$VERIFY_API/api/agents/knowledge-analyst/runs")
printf '%s' "$runs" | python3 -c '
import json,sys
values=json.load(sys.stdin)
run=next(item for item in values if item["details"].get("memory_scope",{}).get("session_id")=="phase9-offline-session")
details=run["details"]
assert details["skills_loaded"]==["knowledge-analysis"]
assert details["mcp_loaded"]==["demo-database-mcp","demo-filesystem-mcp"]
assert details["knowledge_loaded"]==["company-docs"]
assert {call["tool"] for call in details["mcp_calls"]}=={"filesystem_read","database_query"}
assert all(call["status"]=="succeeded" for call in details["mcp_calls"])
'

source_ids_after=$($SOURCE_COMPOSE ps -q | sort)
test "$source_ids_before" = "$source_ids_after"

(
  cd "$VERIFY_ROOT"
  $VERIFY_COMPOSE down --remove-orphans
)
rm -rf -- "$VERIFY_ROOT"

test "$source_ids_before" = "$($SOURCE_COMPOSE ps -q | sort)"
echo "Phase 9 offline deployment validation passed"
