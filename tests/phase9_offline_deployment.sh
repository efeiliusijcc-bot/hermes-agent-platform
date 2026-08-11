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
VERIFY_INTERNAL_NETWORK=hermes-agent-platform-offline-verify-internal
VERIFY_EDGE_NETWORK=hermes-agent-platform-offline-verify-edge
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

if [ -f "$VERIFY_ROOT/docker-compose.yml" ]; then
  (
    cd "$VERIFY_ROOT"
    HERMES_INTERNAL_NETWORK_NAME=$VERIFY_INTERNAL_NETWORK \
    HERMES_EDGE_NETWORK_NAME=$VERIFY_EDGE_NETWORK \
      docker compose -p "$VERIFY_PROJECT" down --remove-orphans
  )
fi
rm -rf -- "$VERIFY_ROOT"
mkdir -p "$VERIFY_ROOT"
tar -xzf "$ARCHIVE" -C "$VERIFY_ROOT" --strip-components=1

OFFLINE_PROJECT_NAME=$VERIFY_PROJECT \
OFFLINE_AGENT_API_PORT=$VERIFY_PORT \
OFFLINE_INTERNAL_NETWORK_NAME=$VERIFY_INTERNAL_NETWORK \
OFFLINE_EDGE_NETWORK_NAME=$VERIFY_EDGE_NETWORK \
  "$VERIFY_ROOT/scripts/restore-offline-bundle.sh"

set -a
. "$VERIFY_ROOT/.env"
set +a
HERMES_COMPOSE_PROJECT_NAME=$VERIFY_PROJECT
HERMES_INTERNAL_NETWORK_NAME=$VERIFY_INTERNAL_NETWORK
HERMES_EDGE_NETWORK_NAME=$VERIFY_EDGE_NETWORK
AGENT_API_PORT=$VERIFY_PORT
export HERMES_COMPOSE_PROJECT_NAME HERMES_INTERNAL_NETWORK_NAME HERMES_EDGE_NETWORK_NAME AGENT_API_PORT
VERIFY_COMPOSE="docker compose -p $VERIFY_PROJECT -f $VERIFY_ROOT/docker-compose.yml"
VERIFY_API="http://127.0.0.1:$VERIFY_PORT"

test "$($VERIFY_COMPOSE ps --status running -q | wc -l | tr -d ' ')" = "8"
curl -fsS "$VERIFY_API/health" | python3 -c 'import json,sys; assert json.load(sys.stdin)=={"status":"ok","database":"ok","memory":"ok","knowledge":"ok"}'

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
