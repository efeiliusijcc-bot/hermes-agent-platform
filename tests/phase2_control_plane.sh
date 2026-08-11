#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
API_URL="http://${AGENT_API_TEST_HOST:-127.0.0.1}:${AGENT_API_PORT:-18088}"
COMPOSE="docker compose -p hermes-agent-platform -f $PROJECT_ROOT/docker-compose.yml"
AGENT_ID="phase2-knowledge-agent"

curl -fsS "$API_URL/health" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value == {"status":"ok","database":"ok","memory":"ok","knowledge":"ok"}'

curl -sS -o /dev/null -X DELETE "$API_URL/api/agents/$AGENT_ID" || true

created=$(curl -fsS -X POST "$API_URL/api/agents" \
  -H 'Content-Type: application/json' \
  --data '{
    "id": "phase2-knowledge-agent",
    "name": "知识分析Agent",
    "description": "Phase 2 integration test",
    "role": "知识分析专家",
    "system_prompt": "只根据可靠数据回答",
    "model_config": {"model": "qwen-300b", "temperature": 0.1},
    "status": "active"
  }')
printf '%s' "$created" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["id"]=="phase2-knowledge-agent"; assert value["model_config"]["model"]=="qwen-300b"; assert value["status"]=="active"'

duplicate_status=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/agents" \
  -H 'Content-Type: application/json' \
  --data '{"id":"phase2-knowledge-agent","name":"duplicate","role":"test","system_prompt":"test"}')
test "$duplicate_status" = "409"

listed=$(curl -fsS "$API_URL/api/agents")
printf '%s' "$listed" | python3 -c 'import json,sys; values=json.load(sys.stdin); assert any(item["id"]=="phase2-knowledge-agent" for item in values)'

detail=$(curl -fsS "$API_URL/api/agents/$AGENT_ID")
printf '%s' "$detail" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["role"]=="知识分析专家"; assert value["model_config"]["temperature"]==0.1'

database_count=$($COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT count(*) FROM agents WHERE id = '$AGENT_ID' AND model_config->>'model' = 'qwen-300b'")
test "$database_count" = "1"

curl -fsS -o /dev/null -X DELETE "$API_URL/api/agents/$AGENT_ID"
missing_status=$(curl -sS -o /dev/null -w '%{http_code}' "$API_URL/api/agents/$AGENT_ID")
test "$missing_status" = "404"

echo "Phase 2 control plane validation passed"
