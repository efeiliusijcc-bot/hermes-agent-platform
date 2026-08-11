#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
API_URL="http://${AGENT_API_TEST_HOST:-127.0.0.1}:${AGENT_API_PORT:-18088}"
COMPOSE="docker compose -p hermes-agent-platform -f $PROJECT_ROOT/docker-compose.yml"
AGENT_ID="phase4-knowledge-agent"
SKILL_ID="knowledge-analysis"

curl -sS -o /dev/null -X DELETE "$API_URL/api/agents/$AGENT_ID" || true
curl -sS -o /dev/null -X DELETE "$API_URL/api/skills/$SKILL_ID" || true

invalid_status=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/skills" \
  -H 'Content-Type: application/json' \
  --data '{"id":"missing-skill","name":"Missing Skill","path":"missing-skill"}')
test "$invalid_status" = "422"

created_skill=$(curl -fsS -X POST "$API_URL/api/skills" \
  -H 'Content-Type: application/json' \
  --data '{
    "id": "knowledge-analysis",
    "name": "Knowledge Analysis",
    "description": "Phase 4 knowledge analysis workflow",
    "path": "knowledge-analysis"
  }')
printf '%s' "$created_skill" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["id"]=="knowledge-analysis"; assert value["path"]=="knowledge-analysis"'

duplicate_status=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/skills" \
  -H 'Content-Type: application/json' \
  --data '{"id":"knowledge-analysis","name":"Duplicate","path":"knowledge-analysis"}')
test "$duplicate_status" = "409"

curl -fsS -X POST "$API_URL/api/agents" \
  -H 'Content-Type: application/json' \
  --data '{
    "id": "phase4-knowledge-agent",
    "name": "Phase 4 Knowledge Agent",
    "role": "企业知识分析专家",
    "system_prompt": "严格执行已绑定 Skill 中定义的流程和自动化验收规则。",
    "model_config": {"model": "external-openai-compatible"},
    "status": "active"
  }' >/dev/null

binding=$(curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/skills/$SKILL_ID")
printf '%s' "$binding" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value=={"agent_id":"phase4-knowledge-agent","skill_ids":["knowledge-analysis"]}'

binding_repeat=$(curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/skills/$SKILL_ID")
printf '%s' "$binding_repeat" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["skill_ids"]==["knowledge-analysis"]'

bound_skills=$(curl -fsS "$API_URL/api/agents/$AGENT_ID/skills")
printf '%s' "$bound_skills" | python3 -c 'import json,sys; values=json.load(sys.stdin); assert [item["id"] for item in values]==["knowledge-analysis"]'

run_result=$(curl -fsS --max-time 240 -X POST "$API_URL/api/agents/$AGENT_ID/run" \
  -H 'Content-Type: application/json' \
  --data '{"input":"执行阶段四技能验证"}')
printf '%s' "$run_result" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["status"]=="succeeded"; assert value["output"].strip()=="SKILL_PHASE4_OK"'

runs=$(curl -fsS "$API_URL/api/agents/$AGENT_ID/runs")
printf '%s' "$runs" | python3 -c 'import json,sys; values=json.load(sys.stdin); assert values[0]["status"]=="succeeded"; assert values[0]["details"]["skills_loaded"]==["knowledge-analysis"]'

binding_count=$($COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT count(*) FROM agent_skill WHERE agent_id = '$AGENT_ID' AND skill_id = '$SKILL_ID'")
test "$binding_count" = "1"

$COMPOSE logs --no-color --since=10m agent-api | grep -q "Skill loaded: knowledge-analysis"

curl -fsS -o /dev/null -X DELETE "$API_URL/api/agents/$AGENT_ID/skills/$SKILL_ID"
unbound_status=$(curl -sS -o /dev/null -w '%{http_code}' -X DELETE "$API_URL/api/agents/$AGENT_ID/skills/$SKILL_ID")
test "$unbound_status" = "404"

curl -fsS -o /dev/null -X DELETE "$API_URL/api/agents/$AGENT_ID"
curl -fsS -o /dev/null -X DELETE "$API_URL/api/skills/$SKILL_ID"

echo "Phase 4 skill loader validation passed"
