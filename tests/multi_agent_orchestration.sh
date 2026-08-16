#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
API_URL=${API_URL:-http://${AGENT_API_TEST_HOST:-127.0.0.1}:${MULTI_AGENT_API_PORT:-38588}}
MANAGER_ID=${MULTI_AGENT_MANAGER_ID:-multi-manager}
WORKER_PREFIX=${MULTI_AGENT_WORKER_PREFIX:-multi-worker}
WORKER_COUNT=${MULTI_AGENT_WORKER_COUNT:-10}
TMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/hermes-multi-agent.XXXXXX")
trap 'rm -rf "$TMP_ROOT"' EXIT HUP INT TERM

stage() {
  printf '[multi-agent] %s\n' "$1"
}

json_id() {
  python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])'
}

wait_run_status() {
  run_id=$1
  expected=$2
  attempts=${3:-120}
  index=0
  while [ "$index" -lt "$attempts" ]; do
    body=$(curl -fsS "$API_URL/api/workflow-runs/$run_id")
    current=$(printf '%s' "$body" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')
    if [ "$current" = "$expected" ]; then
      printf '%s' "$body"
      return 0
    fi
    if [ "$current" = "failed" ] || [ "$current" = "cancelled" ]; then
      printf '[multi-agent] run %s ended unexpectedly: %s\n' "$run_id" "$body" >&2
      return 1
    fi
    sleep 2
    index=$((index + 1))
  done
  printf '[multi-agent] run %s did not reach %s\n' "$run_id" "$expected" >&2
  return 1
}

stage "checking control-plane health"
curl -fsS "$API_URL/health" |
  python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["status"]=="ok" and v["agent_message_bus"]=="ok"'

stage "creating Manager and $WORKER_COUNT Worker Agents"
curl -fsS -X POST "$API_URL/api/agents" -H 'Content-Type: application/json' --data "{
  \"id\":\"$MANAGER_ID\",\"name\":\"Multi Agent Manager\",\"description\":\"verification manager\",
  \"agent_type\":\"manager\",\"role\":\"manager\",\"system_prompt\":\"Aggregate all worker evidence.\",
  \"model\":\"multi-agent-model\",\"model_adapter\":\"qwen\",\"runtime_type\":\"hermes\",
  \"status\":\"active\",\"response_mode\":\"sync\"
}" >/dev/null

index=1
while [ "$index" -le "$WORKER_COUNT" ]; do
  worker_id="$WORKER_PREFIX-$index"
  curl -fsS -X POST "$API_URL/api/agents" -H 'Content-Type: application/json' --data "{
    \"id\":\"$worker_id\",\"name\":\"Worker $index\",\"description\":\"isolated worker\",
    \"agent_type\":\"worker\",\"parent_agent_id\":\"$MANAGER_ID\",\"role\":\"analysis-$index\",
    \"system_prompt\":\"Return a concise verified result.\",\"model\":\"multi-agent-model\",
    \"model_adapter\":\"qwen\",\"runtime_type\":\"hermes\",\"status\":\"active\"
  }" >/dev/null
  index=$((index + 1))
done

stage "creating Team and member bindings"
TEAM_ID=$(curl -fsS -X POST "$API_URL/api/agent-teams" -H 'Content-Type: application/json' --data "{
  \"name\":\"Multi Agent Verification Team\",\"description\":\"10 Agent concurrency contract\",
  \"owner_agent_id\":\"$MANAGER_ID\",\"status\":\"active\"
}" | json_id)

index=1
while [ "$index" -le "$WORKER_COUNT" ]; do
  worker_id="$WORKER_PREFIX-$index"
  curl -fsS -X PUT "$API_URL/api/agent-teams/$TEAM_ID/members/$worker_id" \
    -H 'Content-Type: application/json' --data "{\"role\":\"analysis-$index\",\"priority\":$((100 - index))}" >/dev/null
  index=$((index + 1))
done

curl -fsS "$API_URL/api/agent-teams/$TEAM_ID" |
  python3 -c 'import json,sys; v=json.load(sys.stdin); expected=int(sys.argv[1])+1; assert len(v["members"])==expected; assert sum(x["agent_type"]=="manager" for x in v["members"])==1' "$WORKER_COUNT"

stage "running $WORKER_COUNT Workers concurrently and Manager aggregation"
RUN_ID=$(curl -fsS -X POST "$API_URL/api/agent-teams/$TEAM_ID/runs" \
  -H 'Content-Type: application/json' --data '{
    "input":"Analyze the renewable energy sector from each assigned perspective.",
    "session_id":"multi-agent-concurrency","priority":8
  }' | json_id)
wait_run_status "$RUN_ID" succeeded 180 > "$TMP_ROOT/team-run.json"
curl -fsS "$API_URL/api/workflow-runs/$RUN_ID/tasks" > "$TMP_ROOT/team-tasks.json"
python3 - "$WORKER_COUNT" "$TMP_ROOT/team-tasks.json" <<'PY'
import json, pathlib, sys
worker_count = int(sys.argv[1])
tasks = json.loads(pathlib.Path(sys.argv[2]).read_text())
assert len(tasks) == worker_count + 1
assert len({task["session_id"] for task in tasks}) == worker_count + 1
assert all(task["status"] == "succeeded" for task in tasks)
roots = [task for task in tasks if task["parent_task_id"] is None]
children = [task for task in tasks if task["parent_task_id"] is not None]
assert len(roots) == 1 and roots[0]["node_key"] == "__manager__"
assert len(children) == worker_count
assert all(task["parent_task_id"] == roots[0]["id"] for task in children)
assert all(task["attempt"] >= 1 for task in tasks)
PY

stage "creating DAG with Human Approval"
WORKFLOW_ID=$(curl -fsS -X POST "$API_URL/api/workflows" -H 'Content-Type: application/json' --data "{
  \"team_id\":\"$TEAM_ID\",\"name\":\"Research Review Workflow\",\"status\":\"active\",
  \"nodes\":[
    {\"key\":\"research\",\"type\":\"agent\",\"name\":\"Research\",\"agent_id\":\"$WORKER_PREFIX-1\",\"depends_on\":[],\"config\":{}},
    {\"key\":\"analysis\",\"type\":\"agent\",\"name\":\"Analysis\",\"agent_id\":\"$WORKER_PREFIX-2\",\"depends_on\":[\"research\"],\"config\":{}},
    {\"key\":\"approval\",\"type\":\"human_approval\",\"name\":\"Human Approval\",\"agent_id\":\"$MANAGER_ID\",\"depends_on\":[\"analysis\"],\"config\":{}}
  ]
}" | json_id)
WORKFLOW_RUN_ID=$(curl -fsS -X POST "$API_URL/api/workflows/$WORKFLOW_ID/runs" \
  -H 'Content-Type: application/json' --data '{"input":"Produce a reviewed sector brief.","session_id":"multi-agent-approval","priority":7}' | json_id)
wait_run_status "$WORKFLOW_RUN_ID" human_review 180 >/dev/null
APPROVAL_TASK_ID=$(curl -fsS "$API_URL/api/workflow-runs/$WORKFLOW_RUN_ID/tasks" |
  python3 -c 'import json,sys; print(next(x["id"] for x in json.load(sys.stdin) if x["status"]=="human_review"))')
curl -fsS -X POST "$API_URL/api/tasks/$APPROVAL_TASK_ID/approval" \
  -H 'Content-Type: application/json' --data '{"approved":true,"note":"verified by acceptance test"}' >/dev/null
wait_run_status "$WORKFLOW_RUN_ID" succeeded 180 >/dev/null

stage "checking Agent message trace"
curl -fsS "$API_URL/api/agent-messages?to_agent=$MANAGER_ID&limit=500" |
  python3 -c 'import json,sys; v=json.load(sys.stdin); assert len(v)>=int(sys.argv[1]); assert all(x["to_agent"]==sys.argv[2] for x in v); assert any(x["message_type"]=="result" for x in v)' "$WORKER_COUNT" "$MANAGER_ID"

stage "Multi-Agent acceptance passed"
