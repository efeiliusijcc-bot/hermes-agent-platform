#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
API_URL="http://${AGENT_API_TEST_HOST:-127.0.0.1}:${AGENT_API_PORT:-18088}"
COMPOSE="docker compose -p hermes-agent-platform -f $PROJECT_ROOT/docker-compose.yml"
AGENT_ID="phase3-runtime-agent"

curl -sS -o /dev/null -X DELETE "$API_URL/api/agents/$AGENT_ID" || true
curl -fsS -X POST "$API_URL/api/agents" \
  -H 'Content-Type: application/json' \
  --data '{
    "id": "phase3-runtime-agent",
    "name": "Hermes Runtime Agent",
    "role": "严格指令执行器",
    "system_prompt": "用户要求输出验证标记时，必须原样输出该标记，不添加解释。",
    "model_config": {"model": "external-openai-compatible"},
    "status": "active"
  }' >/dev/null

run_result=$(curl -fsS --max-time 240 -X POST "$API_URL/api/agents/$AGENT_ID/run" \
  -H 'Content-Type: application/json' \
  --data '{"input":"只输出 HERMES_PHASE3_OK"}')
printf '%s' "$run_result" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["status"]=="succeeded"; assert "HERMES_PHASE3_OK" in value["output"]; assert value["execution_id"]; assert value["hermes_run_id"]'

runs=$(curl -fsS "$API_URL/api/agents/$AGENT_ID/runs")
printf '%s' "$runs" | python3 -c 'import json,sys; values=json.load(sys.stdin); assert len(values)>=1; assert values[0]["status"]=="succeeded"; assert "HERMES_PHASE3_OK" in values[0]["output"]; assert values[0]["details"]["hermes_run_id"]'

database_count=$($COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT count(*) FROM execution_logs WHERE agent_id = '$AGENT_ID' AND status = 'succeeded' AND output LIKE '%HERMES_PHASE3_OK%'")
test "$database_count" -ge 1

curl -fsS -o /dev/null -X DELETE "$API_URL/api/agents/$AGENT_ID"
echo "Phase 3 Hermes runtime validation passed"
