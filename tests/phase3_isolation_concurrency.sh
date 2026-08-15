#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
API_URL="http://${AGENT_API_TEST_HOST:-127.0.0.1}:${AGENT_API_PORT:-18088}"
PROJECT_NAME=${HERMES_COMPOSE_PROJECT_NAME:-${COMPOSE_PROJECT_NAME:-hermes-agent-platform}}
COMPOSE_FILES=${HERMES_COMPOSE_FILES:-"-f $PROJECT_ROOT/docker-compose.yml"}
COMPOSE="docker compose -p $PROJECT_NAME $COMPOSE_FILES"
AGENT_A=phase3-report-agent
AGENT_B=phase3-review-agent

cleanup() {
  curl -sS -o /dev/null -X DELETE "$API_URL/api/agents/$AGENT_A" || true
  curl -sS -o /dev/null -X DELETE "$API_URL/api/agents/$AGENT_B" || true
}
trap cleanup EXIT HUP INT TERM
cleanup
$COMPOSE ps --status running model-stub | grep -q 'model-stub'
curl -fsS "$API_URL/health" | python3 -c 'import json,sys; v=json.load(sys.stdin); assert all(v.get(k)=="ok" for k in ("status","database","memory","knowledge","queue","artifact_storage"))'

create_agent() {
  id=$1
  curl -fsS -X POST "$API_URL/api/agents" -H 'Content-Type: application/json' \
    --data "{\"id\":\"$id\",\"name\":\"$id\",\"role\":\"Phase 3 validation\",\"system_prompt\":\"Return a short deterministic answer.\",\"model\":\"phase3-model\",\"model_adapter\":\"qwen\",\"prompt_template\":\"{{input}}\",\"model_config\":{},\"status\":\"active\"}" >/dev/null
}
create_agent "$AGENT_A"
create_agent "$AGENT_B"

task_a=$(curl -fsS -X POST "$API_URL/api/agents/$AGENT_A/tasks" -H 'Content-Type: application/json' --data '{"input":"PHASE3_AGENT_A","session_id":"shared-memory-key","priority":9}')
task_b=$(curl -fsS -X POST "$API_URL/api/agents/$AGENT_B/tasks" -H 'Content-Type: application/json' --data '{"input":"PHASE3_AGENT_B","session_id":"shared-memory-key","priority":5}')
task_a_id=$(printf '%s' "$task_a" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
task_b_id=$(printf '%s' "$task_b" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

wait_task() {
  task_id=$1
  attempt=0
  while [ "$attempt" -lt 90 ]; do
    value=$(curl -fsS "$API_URL/api/tasks/$task_id")
    state=$(printf '%s' "$value" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')
    case "$state" in
      succeeded) printf '%s' "$value"; return 0 ;;
      failed|cancelled) printf '%s\n' "$value" >&2; return 1 ;;
    esac
    attempt=$((attempt + 1))
    sleep 1
  done
  echo "task $task_id did not finish" >&2
  return 1
}
wait_task "$task_a_id" >/dev/null
wait_task "$task_b_id" >/dev/null

sessions_a=$(curl -fsS "$API_URL/api/sessions?agent_id=$AGENT_A")
sessions_b=$(curl -fsS "$API_URL/api/sessions?agent_id=$AGENT_B")
session_a=$(printf '%s' "$sessions_a" | python3 -c 'import json,sys; v=json.load(sys.stdin); assert len(v)==1 and v[0]["status"]=="succeeded" and v[0]["memory_session_id"]=="shared-memory-key"; print(v[0]["id"])')
session_b=$(printf '%s' "$sessions_b" | python3 -c 'import json,sys; v=json.load(sys.stdin); assert len(v)==1 and v[0]["status"]=="succeeded" and v[0]["memory_session_id"]=="shared-memory-key"; print(v[0]["id"])')
test "$session_a" != "$session_b"
curl -fsS "$API_URL/api/sessions/$session_a" | python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["agent_id"]=="phase3-report-agent" and v["status"]=="succeeded"'
curl -fsS "$API_URL/api/sessions/$session_b" | python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["agent_id"]=="phase3-review-agent" and v["status"]=="succeeded"'

artifacts_a=$(curl -fsS "$API_URL/api/artifacts?agent_id=$AGENT_A")
artifacts_b=$(curl -fsS "$API_URL/api/artifacts?agent_id=$AGENT_B")
artifact_a=$(printf '%s' "$artifacts_a" | python3 -c 'import json,sys; v=json.load(sys.stdin); assert len(v)==1 and v[0]["filename"]=="result.txt" and len(v[0]["sha256"])==64; print(v[0]["id"])')
artifact_b=$(printf '%s' "$artifacts_b" | python3 -c 'import json,sys; v=json.load(sys.stdin); assert len(v)==1 and v[0]["filename"]=="result.txt" and len(v[0]["sha256"])==64; print(v[0]["id"])')
sha_a=$(printf '%s' "$artifacts_a" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["sha256"])')
sha_b=$(printf '%s' "$artifacts_b" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["sha256"])')
curl -fsS "$API_URL/api/artifacts/$artifact_a" | python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["agent_id"]=="phase3-report-agent" and v["filename"]=="result.txt" and v["storage_type"]=="minio"'
curl -fsS "$API_URL/api/artifacts/$artifact_b" | python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["agent_id"]=="phase3-review-agent" and v["filename"]=="result.txt" and v["storage_type"]=="minio"'
content_a=$(curl -fsS "$API_URL/api/artifacts/$artifact_a/download")
content_b=$(curl -fsS "$API_URL/api/artifacts/$artifact_b/download")
printf '%s' "$content_a" | grep -q 'PHASE3_AGENT_A'
printf '%s' "$content_b" | grep -q 'PHASE3_AGENT_B'
test "$(printf '%s' "$content_a" | sha256sum | awk '{print $1}')" = "$sha_a"
test "$(printf '%s' "$content_b" | sha256sum | awk '{print $1}')" = "$sha_b"
if printf '%s' "$content_a" | grep -q 'PHASE3_AGENT_B'; then exit 1; fi
if printf '%s' "$content_b" | grep -q 'PHASE3_AGENT_A'; then exit 1; fi

workspace_a=$(curl -fsS "$API_URL/api/agents/$AGENT_A/workspace")
workspace_b=$(curl -fsS "$API_URL/api/agents/$AGENT_B/workspace")
printf '%s' "$workspace_a" | python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["root"]=="phase3-report-agent/sessions" and v["session_count"]==1 and v["artifact_count"]==1'
printf '%s' "$workspace_b" | python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["root"]=="phase3-review-agent/sessions" and v["session_count"]==1 and v["artifact_count"]==1'

$COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "SELECT count(*) FROM agent_tasks WHERE id IN ('$task_a_id'::uuid, '$task_b_id'::uuid) AND status='succeeded'" | grep -qx 2
$COMPOSE exec -T agent-worker test -f "/data/workspaces/$AGENT_A/sessions/$session_a/output/result.txt"
$COMPOSE exec -T agent-worker test -f "/data/workspaces/$AGENT_B/sessions/$session_b/output/result.txt"
$COMPOSE exec -T hermes-runtime /opt/hermes/.venv/bin/python -c 'from hermes_cli.config import load_config; c=load_config(); assert c["_config_version"]==33; assert c["terminal"]["cwd"]=="/opt/data"; assert c["terminal"]["home_mode"]=="auto"'
$COMPOSE exec -T hermes-runtime test -d /opt/data
$COMPOSE exec -T hermes-runtime test ! -e /workspace
model_health=$($COMPOSE exec -T model-gateway python -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8080/health").read().decode())')
printf '%s' "$model_health" | python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["active"]==0; assert 1 <= v["peak"] <= v["max_concurrency"] == 2'

echo "Phase 3 Agent isolation, Session, Workspace, Artifact, Task Queue, and Worker validation passed"
