#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
API_URL="http://${AGENT_API_TEST_HOST:-127.0.0.1}:${AGENT_API_PORT:-18088}"
PROJECT_NAME=${HERMES_COMPOSE_PROJECT_NAME:-hermes-agent-platform}
COMPOSE="docker compose -p $PROJECT_NAME -f $PROJECT_ROOT/docker-compose.yml"
AGENT_ID="knowledge-analyst"
SKILL_ID="knowledge-analysis"
FILESYSTEM_ID="demo-filesystem-mcp"
DATABASE_ID="demo-database-mcp"
SOURCE_ID="company-docs"
MCP_ENDPOINT="http://mcp-gateway:8090/mcp"
AGENT_CONFIG="$PROJECT_ROOT/configs/knowledge-analyst-demo/agent.json"
KNOWLEDGE_FIXTURE="$PROJECT_ROOT/tests/fixtures/knowledge/company-ai-applications.md"
FILE_FIXTURE="$PROJECT_ROOT/tests/fixtures/mcp-files/knowledge-agent-ai-operations.txt"
RUNTIME_FILE="$PROJECT_ROOT/data/mcp-files/knowledge-agent-ai-operations.txt"

delete_owned_resource() {
  resource_url=$1
  resource_name=$2
  resource_status=$(curl -sS -o /dev/null -w '%{http_code}' -X DELETE "$resource_url")
  case "$resource_status" in
    204|404) ;;
    *)
      echo "Could not reset demo resource $resource_name (HTTP $resource_status)" >&2
      exit 1
      ;;
  esac
}

curl -fsS "$API_URL/health" >/dev/null

delete_owned_resource "$API_URL/api/agents/$AGENT_ID" "$AGENT_ID"
delete_owned_resource "$API_URL/api/knowledge-sources/$SOURCE_ID" "$SOURCE_ID"
delete_owned_resource "$API_URL/api/mcp-servers/$FILESYSTEM_ID" "$FILESYSTEM_ID"
delete_owned_resource "$API_URL/api/mcp-servers/$DATABASE_ID" "$DATABASE_ID"

skill_status=$(curl -sS -o /dev/null -w '%{http_code}' "$API_URL/api/skills/$SKILL_ID")
case "$skill_status" in
  200)
    skill=$(curl -fsS "$API_URL/api/skills/$SKILL_ID")
    printf '%s' "$skill" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["id"]=="knowledge-analysis"; assert value["path"]=="knowledge-analysis"'
    ;;
  404)
    curl -fsS -X POST "$API_URL/api/skills" \
      -H 'Content-Type: application/json' \
      --data '{"id":"knowledge-analysis","name":"Knowledge Analysis","description":"企业知识分析工作流","path":"knowledge-analysis"}' >/dev/null
    ;;
  *)
    echo "Could not inspect Skill $SKILL_ID (HTTP $skill_status)" >&2
    exit 1
    ;;
esac

mkdir -p "$PROJECT_ROOT/data/mcp-files"
cp "$FILE_FIXTURE" "$RUNTIME_FILE"
chmod 0640 "$RUNTIME_FILE"
chown "${MCP_GATEWAY_UID:-10001}:${MCP_GATEWAY_GID:-10001}" "$RUNTIME_FILE"

$COMPOSE exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL'
CREATE TABLE IF NOT EXISTS knowledge_agent_ai_metrics (
  department text PRIMARY KEY,
  adoption_percent integer NOT NULL CHECK (adoption_percent BETWEEN 0 AND 100),
  active_projects integer NOT NULL CHECK (active_projects >= 0),
  evidence_marker text NOT NULL
);
TRUNCATE TABLE knowledge_agent_ai_metrics;
INSERT INTO knowledge_agent_ai_metrics(department, adoption_percent, active_projects, evidence_marker)
VALUES
  ('客服', 68, 4, 'TITAN_DATABASE_SIGNAL_93'),
  ('研发', 82, 7, 'TITAN_DATABASE_SIGNAL_93'),
  ('运营', 55, 3, 'TITAN_DATABASE_SIGNAL_93');
SQL

curl -fsS -X POST "$API_URL/api/mcp-servers" \
  -H 'Content-Type: application/json' \
  --data "{\"id\":\"$FILESYSTEM_ID\",\"name\":\"Knowledge Demo Filesystem MCP\",\"endpoint\":\"$MCP_ENDPOINT\",\"config\":{\"kind\":\"filesystem\",\"read_only\":true}}" >/dev/null
curl -fsS -X POST "$API_URL/api/mcp-servers" \
  -H 'Content-Type: application/json' \
  --data "{\"id\":\"$DATABASE_ID\",\"name\":\"Knowledge Demo Database MCP\",\"endpoint\":\"$MCP_ENDPOINT\",\"config\":{\"kind\":\"database\",\"read_only\":true}}" >/dev/null

curl -fsS -X POST "$API_URL/api/knowledge-sources" \
  -H 'Content-Type: application/json' \
  --data '{"id":"company-docs","name":"Company Documents","description":"公司 AI 应用知识文档","status":"active"}' >/dev/null
curl -fsS -X POST "$API_URL/api/knowledge-sources/$SOURCE_ID/documents" \
  -F "file=@$KNOWLEDGE_FIXTURE;filename=company-ai-applications.md;type=text/markdown" >/dev/null

curl -fsS -X POST "$API_URL/api/agents" \
  -H 'Content-Type: application/json' \
  --data-binary "@$AGENT_CONFIG" >/dev/null
curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/skills/$SKILL_ID" >/dev/null
curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/mcp-servers/$FILESYSTEM_ID" >/dev/null
curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/mcp-servers/$DATABASE_ID" >/dev/null
curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/knowledge-sources/$SOURCE_ID" >/dev/null

echo "Knowledge Analyst demo configured"
