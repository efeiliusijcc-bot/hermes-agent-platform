#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
API_URL="http://${AGENT_API_TEST_HOST:-127.0.0.1}:${AGENT_API_PORT:-18088}"
PROJECT_NAME=${HERMES_COMPOSE_PROJECT_NAME:-hermes-agent-platform}
COMPOSE="docker compose -p $PROJECT_NAME -f $PROJECT_ROOT/docker-compose.yml"
AGENT_ID="phase5-mcp-agent"
FILESYSTEM_ID="filesystem-mcp"
DATABASE_ID="database-mcp"
MCP_ENDPOINT="http://mcp-gateway:8090/mcp"
TEST_FILE="$PROJECT_ROOT/data/mcp-files/company-ai.txt"

curl -sS -o /dev/null -X DELETE "$API_URL/api/agents/$AGENT_ID" || true
curl -sS -o /dev/null -X DELETE "$API_URL/api/mcp-servers/$FILESYSTEM_ID" || true
curl -sS -o /dev/null -X DELETE "$API_URL/api/mcp-servers/$DATABASE_ID" || true
mkdir -p "$PROJECT_ROOT/data/mcp-files"
cp "$PROJECT_ROOT/tests/fixtures/mcp-files/company-ai.txt" "$TEST_FILE"
chmod 0640 "$TEST_FILE"
chown "${MCP_GATEWAY_UID:-10001}:${MCP_GATEWAY_GID:-10001}" "$TEST_FILE"

$COMPOSE exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL'
CREATE TABLE IF NOT EXISTS mcp_business_metrics (
  metric text PRIMARY KEY,
  value integer NOT NULL
);
TRUNCATE TABLE mcp_business_metrics;
INSERT INTO mcp_business_metrics(metric, value)
VALUES ('NEBULA_DATABASE_SIGNAL', 42);
SQL

non_readonly_status=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/mcp-servers" \
  -H 'Content-Type: application/json' \
  --data "{\"id\":\"unsafe-mcp\",\"name\":\"Unsafe\",\"endpoint\":\"$MCP_ENDPOINT\",\"config\":{\"kind\":\"database\",\"read_only\":false}}")
test "$non_readonly_status" = "422"

wrong_endpoint_status=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/mcp-servers" \
  -H 'Content-Type: application/json' \
  --data '{"id":"wrong-endpoint","name":"Wrong","endpoint":"http://example.invalid/mcp","config":{"kind":"filesystem","read_only":true}}')
test "$wrong_endpoint_status" = "422"

filesystem=$(curl -fsS -X POST "$API_URL/api/mcp-servers" \
  -H 'Content-Type: application/json' \
  --data "{\"id\":\"$FILESYSTEM_ID\",\"name\":\"Filesystem MCP\",\"endpoint\":\"$MCP_ENDPOINT\",\"config\":{\"kind\":\"filesystem\",\"read_only\":true}}")
printf '%s' "$filesystem" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["id"]=="filesystem-mcp"; assert value["config"]=={"kind":"filesystem","read_only":True}'

database=$(curl -fsS -X POST "$API_URL/api/mcp-servers" \
  -H 'Content-Type: application/json' \
  --data "{\"id\":\"$DATABASE_ID\",\"name\":\"Database MCP\",\"endpoint\":\"$MCP_ENDPOINT\",\"config\":{\"kind\":\"database\",\"read_only\":true}}")
printf '%s' "$database" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["id"]=="database-mcp"; assert value["config"]["kind"]=="database"'

curl -fsS -X POST "$API_URL/api/agents" \
  -H 'Content-Type: application/json' \
  --data '{
    "id": "phase5-mcp-agent",
    "name": "Phase 5 MCP Agent",
    "role": "只读数据核验员",
    "system_prompt": "必须按用户要求调用所有已绑定 MCP 工具获取真实内容；不得根据文件名或表名猜测结果。调用工具时必须原样传入运行上下文给出的 access_token。",
    "model_config": {"model": "external-openai-compatible"},
    "status": "active"
  }' >/dev/null

curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/mcp-servers/$FILESYSTEM_ID" >/dev/null
binding=$(curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/mcp-servers/$DATABASE_ID")
printf '%s' "$binding" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["mcp_ids"]==["database-mcp","filesystem-mcp"]; assert value["capabilities"]==["database","filesystem"]'

binding_repeat=$(curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/mcp-servers/$DATABASE_ID")
printf '%s' "$binding_repeat" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["mcp_ids"].count("database-mcp")==1'

configured=$($COMPOSE exec -T hermes-runtime /opt/hermes/.venv/bin/hermes mcp list)
printf '%s' "$configured" | grep -q "mcp-gateway"
$COMPOSE exec -T hermes-runtime /opt/hermes/.venv/bin/hermes mcp test mcp-gateway >/dev/null

run_result=$(curl -fsS --max-time 300 -X POST "$API_URL/api/agents/$AGENT_ID/run" \
  -H 'Content-Type: application/json' \
  --data '{"input":"先调用 filesystem_read 读取 company-ai.txt，再调用 database_query 执行 SELECT metric, value FROM mcp_business_metrics ORDER BY metric。完成两次工具调用后，只返回从工具结果中读到的文件证据文本和数据库 metric/value。"}')
printf '%s' "$run_result" | python3 -c 'import json,sys; value=json.load(sys.stdin); output=value["output"]; assert value["status"]=="succeeded"; assert "ORION_FILE_SIGNAL_71" in output; assert "NEBULA_DATABASE_SIGNAL" in output; assert "42" in output'

runs=$(curl -fsS "$API_URL/api/agents/$AGENT_ID/runs")
printf '%s' "$runs" | python3 -c 'import json,sys; values=json.load(sys.stdin); details=values[0]["details"]; assert details["mcp_loaded"]==["database-mcp","filesystem-mcp"]; calls=details["mcp_calls"]; assert [call["tool"] for call in calls]==["filesystem_read","database_query"]; assert all(call["status"]=="succeeded" for call in calls)'

binding_count=$($COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT count(*) FROM agent_mcp WHERE agent_id = '$AGENT_ID'")
test "$binding_count" = "2"

$COMPOSE logs --no-color --since=10m mcp-gateway | grep -q "MCP tool called: filesystem_read"
$COMPOSE logs --no-color --since=10m mcp-gateway | grep -q "MCP tool called: database_query"

curl -fsS -o /dev/null -X DELETE "$API_URL/api/agents/$AGENT_ID/mcp-servers/$FILESYSTEM_ID"
unbound_status=$(curl -sS -o /dev/null -w '%{http_code}' -X DELETE "$API_URL/api/agents/$AGENT_ID/mcp-servers/$FILESYSTEM_ID")
test "$unbound_status" = "404"

curl -fsS -o /dev/null -X DELETE "$API_URL/api/agents/$AGENT_ID"
curl -fsS -o /dev/null -X DELETE "$API_URL/api/mcp-servers/$FILESYSTEM_ID"
curl -fsS -o /dev/null -X DELETE "$API_URL/api/mcp-servers/$DATABASE_ID"
$COMPOSE exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "DROP TABLE mcp_business_metrics" >/dev/null
rm -f "$TEST_FILE"

echo "Phase 5 MCP registry validation passed"
