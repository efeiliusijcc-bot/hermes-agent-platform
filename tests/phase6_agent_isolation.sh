#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
API_URL="http://${AGENT_API_TEST_HOST:-127.0.0.1}:${AGENT_API_PORT:-18088}"
COMPOSE="docker compose -p hermes-agent-platform -f $PROJECT_ROOT/docker-compose.yml"
AGENT_A="phase6-file-agent"
AGENT_B="phase6-database-agent"
SKILL_ID="knowledge-analysis"
FILESYSTEM_ID="filesystem-mcp"
DATABASE_ID="database-mcp"
MCP_ENDPOINT="http://mcp-gateway:8090/mcp"
SESSION_ID="phase6-shared-session"
AGENT_A_MEMORY_KEY="hermes:agent-memory:v1:$AGENT_A:$SESSION_ID"
AGENT_B_MEMORY_KEY="hermes:agent-memory:v1:$AGENT_B:$SESSION_ID"
TEST_FILE="$PROJECT_ROOT/data/mcp-files/phase6-agent-a.txt"

curl -sS -o /dev/null -X DELETE "$API_URL/api/agents/$AGENT_A" || true
curl -sS -o /dev/null -X DELETE "$API_URL/api/agents/$AGENT_B" || true
curl -sS -o /dev/null -X DELETE "$API_URL/api/skills/$SKILL_ID" || true
curl -sS -o /dev/null -X DELETE "$API_URL/api/mcp-servers/$FILESYSTEM_ID" || true
curl -sS -o /dev/null -X DELETE "$API_URL/api/mcp-servers/$DATABASE_ID" || true
$COMPOSE exec -T redis sh -ec 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli DEL "$1" "$2" >/dev/null' sh \
  "$AGENT_A_MEMORY_KEY" "$AGENT_B_MEMORY_KEY"

mkdir -p "$PROJECT_ROOT/data/mcp-files"
cp "$PROJECT_ROOT/tests/fixtures/mcp-files/phase6-agent-a.txt" "$TEST_FILE"
chmod 0640 "$TEST_FILE"
chown "${MCP_GATEWAY_UID:-10001}:${MCP_GATEWAY_GID:-10001}" "$TEST_FILE"

$COMPOSE exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL'
CREATE TABLE IF NOT EXISTS phase6_isolation_metrics (
  metric text PRIMARY KEY,
  value integer NOT NULL
);
TRUNCATE TABLE phase6_isolation_metrics;
INSERT INTO phase6_isolation_metrics(metric, value)
VALUES ('ISOLATION_DATABASE_SIGNAL', 64);
SQL

curl -fsS -X POST "$API_URL/api/skills" \
  -H 'Content-Type: application/json' \
  --data '{"id":"knowledge-analysis","name":"Knowledge Analysis","path":"knowledge-analysis"}' >/dev/null

curl -fsS -X POST "$API_URL/api/mcp-servers" \
  -H 'Content-Type: application/json' \
  --data "{\"id\":\"$FILESYSTEM_ID\",\"name\":\"Filesystem MCP\",\"endpoint\":\"$MCP_ENDPOINT\",\"config\":{\"kind\":\"filesystem\",\"read_only\":true}}" >/dev/null
curl -fsS -X POST "$API_URL/api/mcp-servers" \
  -H 'Content-Type: application/json' \
  --data "{\"id\":\"$DATABASE_ID\",\"name\":\"Database MCP\",\"endpoint\":\"$MCP_ENDPOINT\",\"config\":{\"kind\":\"database\",\"read_only\":true}}" >/dev/null

curl -fsS -X POST "$API_URL/api/agents" \
  -H 'Content-Type: application/json' \
  --data '{
    "id": "phase6-file-agent",
    "name": "Phase 6 File Agent",
    "role": "文件分析 Agent",
    "system_prompt": "只能使用平台明确绑定的工具。要求读取文件时必须调用 filesystem_read 并原样传入 access_token；不得猜测工具结果。",
    "model_config": {"model": "external-openai-compatible"},
    "status": "active"
  }' >/dev/null
curl -fsS -X POST "$API_URL/api/agents" \
  -H 'Content-Type: application/json' \
  --data '{
    "id": "phase6-database-agent",
    "name": "Phase 6 Database Agent",
    "role": "数据库分析 Agent",
    "system_prompt": "只能使用平台明确绑定的工具。要求查询数据库时必须调用 database_query 并原样传入 access_token；不得猜测工具结果。",
    "model_config": {"model": "external-openai-compatible"},
    "status": "active"
  }' >/dev/null

curl -fsS -X PUT "$API_URL/api/agents/$AGENT_A/skills/$SKILL_ID" >/dev/null
curl -fsS -X PUT "$API_URL/api/agents/$AGENT_A/mcp-servers/$FILESYSTEM_ID" >/dev/null
curl -fsS -X PUT "$API_URL/api/agents/$AGENT_B/mcp-servers/$DATABASE_ID" >/dev/null

agent_a_skills=$(curl -fsS "$API_URL/api/agents/$AGENT_A/skills")
printf '%s' "$agent_a_skills" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert [item["id"] for item in value]==["knowledge-analysis"]'
agent_b_skills=$(curl -fsS "$API_URL/api/agents/$AGENT_B/skills")
printf '%s' "$agent_b_skills" | python3 -c 'import json,sys; assert json.load(sys.stdin)==[]'

agent_a_mcp=$(curl -fsS "$API_URL/api/agents/$AGENT_A/mcp-servers")
printf '%s' "$agent_a_mcp" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert [(item["id"],item["config"]["kind"]) for item in value]==[("filesystem-mcp","filesystem")]'
agent_b_mcp=$(curl -fsS "$API_URL/api/agents/$AGENT_B/mcp-servers")
printf '%s' "$agent_b_mcp" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert [(item["id"],item["config"]["kind"]) for item in value]==[("database-mcp","database")]'

$COMPOSE exec -T hermes-runtime /opt/hermes/.venv/bin/python - <<'PY'
from hermes_cli.config import load_config

config = load_config()
assert config["platform_toolsets"]["api_server"] == ["mcp-gateway"]
assert config["memory"]["memory_enabled"] is False
assert config["memory"]["user_profile_enabled"] is False
PY
$COMPOSE exec -T agent-api python - <<'PY'
import os

import httpx

response = httpx.get(
    "http://hermes-runtime:8642/v1/toolsets",
    headers={"Authorization": f"Bearer {os.environ['HERMES_API_KEY']}"},
    timeout=10,
)
response.raise_for_status()
assert [item["name"] for item in response.json()["data"] if item["enabled"]] == []
PY
$COMPOSE exec -T hermes-runtime /opt/hermes/.venv/bin/hermes mcp list | grep -q "mcp-gateway"

invalid_session_status=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/agents/$AGENT_A/run" \
  -H 'Content-Type: application/json' \
  --data '{"input":"must not run","session_id":"../shared:session"}')
test "$invalid_session_status" = "422"

denial_execution_id=$(python3 -c 'import uuid; print(uuid.uuid4())')
$COMPOSE exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "INSERT INTO execution_logs(id, agent_id, status, input, details) VALUES ('$denial_execution_id', '$AGENT_A', 'running', 'deterministic database denial probe', jsonb_build_object('mcp_permissions', jsonb_build_object('filesystem', '$FILESYSTEM_ID')))" >/dev/null

mcp_token=$($COMPOSE exec -T -e PHASE6_EXECUTION_ID="$denial_execution_id" agent-api python - <<'PY'
import os
from app.mcp import issue_mcp_access_token

print(issue_mcp_access_token(
    execution_id=os.environ["PHASE6_EXECUTION_ID"],
))
PY
)
test "${#mcp_token}" -le 60
case "$mcp_token" in
  mcp2.*) ;;
  *) echo "unexpected MCP token format" >&2; exit 1 ;;
esac

denied_result=$($COMPOSE exec -T -e PHASE6_MCP_TOKEN="$mcp_token" hermes-runtime /opt/hermes/.venv/bin/python - <<'PY'
import asyncio
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main() -> None:
    async with streamable_http_client("http://mcp-gateway:8090/mcp") as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            result = await session.call_tool(
                "database_query",
                {
                    "access_token": os.environ["PHASE6_MCP_TOKEN"],
                    "sql": "SELECT metric, value FROM phase6_isolation_metrics",
                },
            )
            text = "\n".join(getattr(item, "text", "") for item in result.content)
            assert result.isError is True
            assert "access denied" in text.lower()
            print("database access denied")


asyncio.run(main())
PY
)
test "$denied_result" = "database access denied"

denied_audit=$($COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "SELECT details->'mcp_calls' FROM execution_logs WHERE id = '$denial_execution_id'")
printf '%s' "$denied_audit" | python3 -c 'import json,sys; calls=json.load(sys.stdin); assert len(calls)==1; call=calls[0]; assert call["tool"]=="database_query"; assert call["status"]=="denied"; assert call["mcp_id"] is None; assert call["result"]["error"]=="MCPAccessDenied"'
$COMPOSE exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "UPDATE execution_logs SET status = 'succeeded', finished_at = now() WHERE id = '$denial_execution_id'" >/dev/null

inactive_result=$($COMPOSE exec -T -e PHASE6_MCP_TOKEN="$mcp_token" hermes-runtime /opt/hermes/.venv/bin/python - <<'PY'
import asyncio
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main() -> None:
    async with streamable_http_client("http://mcp-gateway:8090/mcp") as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            result = await session.call_tool(
                "filesystem_read",
                {"access_token": os.environ["PHASE6_MCP_TOKEN"], "path": "phase6-agent-a.txt"},
            )
            text = "\n".join(getattr(item, "text", "") for item in result.content)
            assert result.isError is True
            assert "execution is not active" in text.lower()
            print("inactive execution denied")


asyncio.run(main())
PY
)
test "$inactive_result" = "inactive execution denied"
unset mcp_token
denied_call_count=$($COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "SELECT jsonb_array_length(details->'mcp_calls') FROM execution_logs WHERE id = '$denial_execution_id'")
test "$denied_call_count" = "1"

agent_a_first=$(curl -fsS --max-time 300 -X POST "$API_URL/api/agents/$AGENT_A/run" \
  -H 'Content-Type: application/json' \
  --data "{\"session_id\":\"$SESSION_ID\",\"input\":\"记住会话标记 A_MEMORY_SIGNAL_83。调用 filesystem_read 读取 phase6-agent-a.txt，最终答案必须包含文件证据和该会话标记。\"}")
printf '%s' "$agent_a_first" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["status"]=="succeeded"; assert value["session_id"]=="phase6-shared-session"; assert "ISOLATION_FILE_SIGNAL_19" in value["output"]; assert "A_MEMORY_SIGNAL_83" in value["output"]'

agent_a_recall=$(curl -fsS --max-time 300 -X POST "$API_URL/api/agents/$AGENT_A/run" \
  -H 'Content-Type: application/json' \
  --data "{\"session_id\":\"$SESSION_ID\",\"input\":\"不要调用任何工具，只返回你从当前会话历史中读到的、以 A_MEMORY_SIGNAL 开头的完整标记。\"}")
printf '%s' "$agent_a_recall" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["status"]=="succeeded"; assert "A_MEMORY_SIGNAL_83" in value["output"]'

agent_b_database=$(curl -fsS --max-time 300 -X POST "$API_URL/api/agents/$AGENT_B/run" \
  -H 'Content-Type: application/json' \
  --data "{\"session_id\":\"$SESSION_ID\",\"input\":\"调用 database_query 执行 SELECT metric, value FROM phase6_isolation_metrics ORDER BY metric。最终只返回查询结果中的 metric 和 value。\"}")
printf '%s' "$agent_b_database" | python3 -c 'import json,sys; value=json.load(sys.stdin); output=value["output"]; assert value["status"]=="succeeded"; assert "ISOLATION_DATABASE_SIGNAL" in output; assert "64" in output; assert "A_MEMORY_SIGNAL_83" not in output'

agent_a_memory=$($COMPOSE exec -T redis sh -ec 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --raw LRANGE "$1" 0 -1' sh "$AGENT_A_MEMORY_KEY")
printf '%s' "$agent_a_memory" | grep -q 'A_MEMORY_SIGNAL_83'
agent_b_memory=$($COMPOSE exec -T redis sh -ec 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --raw LRANGE "$1" 0 -1' sh "$AGENT_B_MEMORY_KEY")
if printf '%s' "$agent_b_memory" | grep -q 'A_MEMORY_SIGNAL_83'; then
  echo "Agent B memory leaked Agent A content" >&2
  exit 1
fi
test "$($COMPOSE exec -T redis sh -ec 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli EXISTS "$1"' sh "$AGENT_A_MEMORY_KEY")" = "1"
test "$($COMPOSE exec -T redis sh -ec 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli EXISTS "$1"' sh "$AGENT_B_MEMORY_KEY")" = "1"

agent_a_runs=$(curl -fsS "$API_URL/api/agents/$AGENT_A/runs")
printf '%s' "$agent_a_runs" | python3 -c '
import json,sys
values=json.load(sys.stdin)
runtime=[item for item in values if item["details"].get("memory_scope",{}).get("session_id")=="phase6-shared-session"]
assert len(runtime)==2
assert all(item["details"]["skills_loaded"]==["knowledge-analysis"] for item in runtime)
assert all(item["details"]["mcp_loaded"]==["filesystem-mcp"] for item in runtime)
assert any(item["details"]["memory_scope"]["history_messages_loaded"]>=2 for item in runtime)
assert any(call["status"]=="denied" and call["tool"]=="database_query" for item in values for call in item["details"].get("mcp_calls",[]))
assert any(call["status"]=="succeeded" and call["tool"]=="filesystem_read" for item in runtime for call in item["details"].get("mcp_calls",[]))
'
agent_b_runs=$(curl -fsS "$API_URL/api/agents/$AGENT_B/runs")
printf '%s' "$agent_b_runs" | python3 -c '
import json,sys
values=json.load(sys.stdin)
assert len(values)==1
details=values[0]["details"]
assert details["skills_loaded"]==[]
assert details["mcp_loaded"]==["database-mcp"]
assert details["memory_scope"]["history_messages_loaded"]==0
assert any(call["status"]=="succeeded" and call["tool"]=="database_query" for call in details["mcp_calls"])
'

token_leaks=$($COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "SELECT count(*) FROM execution_logs WHERE agent_id IN ('$AGENT_A', '$AGENT_B') AND (details::text LIKE '%mcp1.%' OR details::text LIKE '%mcp2.%' OR COALESCE(output, '') LIKE '%mcp1.%' OR COALESCE(output, '') LIKE '%mcp2.%' OR COALESCE(error, '') LIKE '%mcp1.%' OR COALESCE(error, '') LIKE '%mcp2.%')")
test "$token_leaks" = "0"
$COMPOSE logs --no-color --since=15m mcp-gateway | grep -q "MCP tool denied: database_query agent=$AGENT_A"

curl -fsS -o /dev/null -X DELETE "$API_URL/api/agents/$AGENT_A"
test "$($COMPOSE exec -T redis sh -ec 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli EXISTS "$1"' sh "$AGENT_A_MEMORY_KEY")" = "0"
test "$($COMPOSE exec -T redis sh -ec 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli EXISTS "$1"' sh "$AGENT_B_MEMORY_KEY")" = "1"
curl -fsS -o /dev/null -X DELETE "$API_URL/api/agents/$AGENT_B"
test "$($COMPOSE exec -T redis sh -ec 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli EXISTS "$1"' sh "$AGENT_B_MEMORY_KEY")" = "0"

curl -fsS -o /dev/null -X DELETE "$API_URL/api/skills/$SKILL_ID"
curl -fsS -o /dev/null -X DELETE "$API_URL/api/mcp-servers/$FILESYSTEM_ID"
curl -fsS -o /dev/null -X DELETE "$API_URL/api/mcp-servers/$DATABASE_ID"
$COMPOSE exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "DROP TABLE phase6_isolation_metrics" >/dev/null
rm -f "$TEST_FILE"

echo "Phase 6 Agent isolation validation passed"
