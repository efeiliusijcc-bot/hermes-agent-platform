#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
API_URL="http://${AGENT_API_TEST_HOST:-127.0.0.1}:${AGENT_API_PORT:-18088}"
COMPOSE="docker compose -p hermes-agent-platform -f $PROJECT_ROOT/docker-compose.yml"
AGENT_ID="knowledge-analyst"
SESSION_ID="phase8-demo-session"

"$PROJECT_ROOT/scripts/setup-knowledge-agent-demo.sh"

agent=$(curl -fsS "$API_URL/api/agents/$AGENT_ID")
printf '%s' "$agent" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["name"]=="Knowledge Analyst Agent"; assert value["role"]=="企业知识分析专家"; assert value["status"]=="active"'

skills=$(curl -fsS "$API_URL/api/agents/$AGENT_ID/skills")
printf '%s' "$skills" | python3 -c 'import json,sys; values=json.load(sys.stdin); assert [item["id"] for item in values]==["knowledge-analysis"]'

mcp=$(curl -fsS "$API_URL/api/agents/$AGENT_ID/mcp-servers")
printf '%s' "$mcp" | python3 -c 'import json,sys; values=json.load(sys.stdin); assert [(item["id"],item["config"]["kind"]) for item in values]==[("demo-database-mcp","database"),("demo-filesystem-mcp","filesystem")]'

knowledge=$(curl -fsS "$API_URL/api/agents/$AGENT_ID/knowledge-sources")
printf '%s' "$knowledge" | python3 -c 'import json,sys; values=json.load(sys.stdin); assert len(values)==1; assert values[0]["id"]=="company-docs"; assert values[0]["status"]=="active"'

documents=$(curl -fsS "$API_URL/api/knowledge-sources/company-docs/documents")
printf '%s' "$documents" | python3 -c 'import json,sys; values=json.load(sys.stdin); assert len(values)==1; assert values[0]["filename"]=="company-ai-applications.md"; assert values[0]["chunk_count"]>=1'

run_result=$(curl -fsS --max-time 300 -X POST "$API_URL/api/agents/$AGENT_ID/run" \
  -H 'Content-Type: application/json' \
  --data "{\"session_id\":\"$SESSION_ID\",\"input\":\"分析公司AI应用情况。\"}")
printf '%s' "$run_result" | python3 -c '
import json,sys
value=json.load(sys.stdin)
output=value["output"]
assert value["status"]=="succeeded"
assert value["session_id"]=="phase8-demo-session"
assert "ATLAS_KNOWLEDGE_SIGNAL_88" in output
assert "LYRA_FILE_SIGNAL_44" in output
assert "TITAN_DATABASE_SIGNAL_93" in output
'

runs=$(curl -fsS "$API_URL/api/agents/$AGENT_ID/runs")
printf '%s' "$runs" | python3 -c '
import json,sys
values=json.load(sys.stdin)
assert len(values)==1
run=values[0]
details=run["details"]
assert run["status"]=="succeeded"
assert run["started_at"] and run["finished_at"] and run["output"]
assert details["skills_loaded"]==["knowledge-analysis"]
assert details["mcp_loaded"]==["demo-database-mcp","demo-filesystem-mcp"]
assert details["knowledge_loaded"]==["company-docs"]
assert details["knowledge_hits"] and all(hit["source_id"]=="company-docs" for hit in details["knowledge_hits"])
assert "ATLAS_KNOWLEDGE_SIGNAL_88" not in json.dumps(details)
calls=details["mcp_calls"]
assert {call["tool"] for call in calls}=={"filesystem_read","database_query"}
assert all(call["status"]=="succeeded" for call in calls)
'

database_rows=$($COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "SELECT count(*) FROM knowledge_agent_ai_metrics WHERE evidence_marker = 'TITAN_DATABASE_SIGNAL_93'")
test "$database_rows" = "3"

token_leaks=$($COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "SELECT count(*) FROM execution_logs WHERE agent_id = '$AGENT_ID' AND (details::text LIKE '%mcp1.%' OR details::text LIKE '%mcp2.%' OR COALESCE(output, '') LIKE '%mcp1.%' OR COALESCE(output, '') LIKE '%mcp2.%' OR COALESCE(error, '') LIKE '%mcp1.%' OR COALESCE(error, '') LIKE '%mcp2.%')")
test "$token_leaks" = "0"

$COMPOSE logs --no-color --since=10m agent-api | grep -q "Skill loaded: knowledge-analysis"
$COMPOSE logs --no-color --since=10m agent-api | grep -q "Knowledge loaded: company-docs"
$COMPOSE logs --no-color --since=10m mcp-gateway | grep -q "MCP tool called: filesystem_read agent=$AGENT_ID"
$COMPOSE logs --no-color --since=10m mcp-gateway | grep -q "MCP tool called: database_query agent=$AGENT_ID"

echo "Phase 8 Knowledge Analyst demo validation passed"
