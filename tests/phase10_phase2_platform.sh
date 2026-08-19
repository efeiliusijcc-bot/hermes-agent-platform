#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
API_URL="http://${AGENT_API_TEST_HOST:-127.0.0.1}:${AGENT_API_PORT:-18088}"
PROJECT_NAME=${HERMES_COMPOSE_PROJECT_NAME:-${COMPOSE_PROJECT_NAME:-hermes-agent-platform}}
COMPOSE="docker compose -p $PROJECT_NAME -f $PROJECT_ROOT/docker-compose.yml"
AGENT_ID=phase2-public-agent
SKILL_ID=phase2-upload-skill
MCP_ID=phase2-filesystem-mcp
TMP_DIR=$(mktemp -d)

test -n "${PLATFORM_MANAGEMENT_API_KEY:-}" || {
  echo "PLATFORM_MANAGEMENT_API_KEY is required for control-plane validation" >&2
  exit 1
}

management_curl() {
  printf 'header = "X-Platform-Management-Key: %s"\n' "$PLATFORM_MANAGEMENT_API_KEY" |
    curl --config - "$@"
}

cleanup() {
  management_curl -sS -o /dev/null -X DELETE "$API_URL/api/agents/$AGENT_ID" || true
  management_curl -sS -o /dev/null -X DELETE "$API_URL/api/skills/$SKILL_ID" || true
  management_curl -sS -o /dev/null -X DELETE "$API_URL/api/mcp-servers/$MCP_ID" || true
  rm -rf -- "$TMP_DIR"
}
trap cleanup EXIT HUP INT TERM

cleanup
models=$(curl -fsS "$API_URL/api/models?enabled_only=true")
MODEL_ID=$(printf '%s' "$models" | python3 -c 'import json,sys; values=json.load(sys.stdin); value=next((item for item in values if item["is_default"]), values[0]); print(value["id"])')
MODEL_ADAPTER=$(printf '%s' "$models" | python3 -c 'import json,sys; values=json.load(sys.stdin); value=next((item for item in values if item["is_default"]), values[0]); print(value["adapter"])')
test -n "$MODEL_ID" && test -n "$MODEL_ADAPTER"
mkdir -p "$TMP_DIR/$SKILL_ID"
cat > "$TMP_DIR/$SKILL_ID/skill.yaml" <<'YAML'
name: phase2-upload-skill
version: 1.0.0
description: Phase 2 uploaded Skill
entry: SKILL.md
tools: []
YAML
cat > "$TMP_DIR/$SKILL_ID/SKILL.md" <<'MARKDOWN'
# Phase 2 Upload Skill

Return structured JSON when the user requests structured output.
MARKDOWN
python3 - "$TMP_DIR" "$SKILL_ID" <<'PY'
import pathlib
import sys
import zipfile

root = pathlib.Path(sys.argv[1])
skill_id = sys.argv[2]
with zipfile.ZipFile(root / "skill.zip", "w", zipfile.ZIP_DEFLATED) as archive:
    for path in sorted((root / skill_id).rglob("*")):
        if path.is_file():
            archive.write(path, path.relative_to(root))
PY

skill=$(management_curl -fsS -X POST "$API_URL/api/skills/upload" -F "file=@$TMP_DIR/skill.zip;type=application/zip")
printf '%s' "$skill" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["id"]=="phase2-upload-skill"; assert value["version"]=="1.0.0"; assert len(value["package_sha256"])==64'
$COMPOSE exec -T agent-api test -f "/app/skills/$SKILL_ID/config.yaml"

mcp=$(management_curl -fsS -X POST "$API_URL/api/mcp-servers" -H 'Content-Type: application/json' --data "{\"id\":\"$MCP_ID\",\"name\":\"Phase 2 Filesystem MCP\",\"endpoint\":\"http://mcp-gateway:8090/mcp\",\"permission\":\"read_only\",\"config\":{\"kind\":\"filesystem\",\"read_only\":true}}")
printf '%s' "$mcp" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["permission"]=="read_only"; assert value["status"]=="unknown"'
mcp_updated=$(management_curl -fsS -X PUT "$API_URL/api/mcp-servers/$MCP_ID" -H 'Content-Type: application/json' --data '{"name":"Phase 2 Filesystem MCP Updated","endpoint":"http://mcp-gateway:8090/mcp","permission":"read_only","config":{"kind":"filesystem","read_only":true}}')
printf '%s' "$mcp_updated" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["name"].endswith("Updated"); assert value["status"]=="unknown"'
mcp_test=$(management_curl -fsS -X POST "$API_URL/api/mcp-servers/$MCP_ID/test")
printf '%s' "$mcp_test" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["status"]=="online"; assert value["latency_ms"]>=0'

management_curl -fsS -X POST "$API_URL/api/agents" -H 'Content-Type: application/json' --data "{\"id\":\"$AGENT_ID\",\"name\":\"Phase 2 Public Agent\",\"role\":\"Structured response Agent\",\"system_prompt\":\"Return only JSON with summary and recommendations fields.\",\"model_config\":{},\"status\":\"active\"}" >/dev/null
schema=$(management_curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/schema" -H 'Content-Type: application/json' --data '{"input_schema":{"topic":{"type":"string","required":true}},"output_schema":{"summary":"string","recommendations":"array"}}')
printf '%s' "$schema" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["input_schema"]["required"]==["topic"]; assert value["output_schema"]["properties"]["recommendations"]["type"]=="array"'
bad_configuration=$(management_curl -sS -o /dev/null -w '%{http_code}' -X PUT "$API_URL/api/agents/$AGENT_ID/configuration" -H 'Content-Type: application/json' --data "{\"system_prompt\":\"Return only JSON.\",\"model\":\"$MODEL_ID\",\"prompt_template\":\"{{undeclared}}\",\"model_adapter\":\"$MODEL_ADAPTER\",\"model_config\":{}}")
test "$bad_configuration" = "422"
configuration=$(management_curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/configuration" -H 'Content-Type: application/json' --data "{\"system_prompt\":\"Return only JSON matching the output contract.\",\"model\":\"$MODEL_ID\",\"prompt_template\":\"OUTPUT_JSON_OK topic={{topic}}\",\"model_adapter\":\"$MODEL_ADAPTER\",\"model_config\":{\"temperature\":0}}")
printf '%s' "$configuration" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["model"]==sys.argv[1]; assert value["model_adapter"]==sys.argv[2]; assert value["prompt_template"]=="OUTPUT_JSON_OK topic={{topic}}"; assert value["model_config"]=={"temperature":0}' "$MODEL_ID" "$MODEL_ADAPTER"
mode=$(management_curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/response-mode" -H 'Content-Type: application/json' --data '{"response_mode":"stream"}')
printf '%s' "$mode" | python3 -c 'import json,sys; assert json.load(sys.stdin)["response_mode"]=="stream"'
management_curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/skills/$SKILL_ID" >/dev/null
management_curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/mcp-servers/$MCP_ID" >/dev/null

secret=$(management_curl -fsS -X POST "$API_URL/api/agents/$AGENT_ID/publication/api-key")
api_key=$(printf '%s' "$secret" | python3 -c 'import json,sys; print(json.load(sys.stdin)["api_key"])')
test -n "$api_key"
version=$(management_curl -fsS -X POST "$API_URL/api/agents/$AGENT_ID/versions" -H 'Content-Type: application/json' --data '{"created_by":"offline-validation"}')
VERSION_ID=$(printf '%s' "$version" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["status"]=="development"; print(value["version"])')
management_curl -fsS -X PATCH "$API_URL/api/agents/$AGENT_ID/versions/$VERSION_ID/status" -H 'Content-Type: application/json' --data '{"status":"testing"}' >/dev/null
management_curl -fsS -X PATCH "$API_URL/api/agents/$AGENT_ID/versions/$VERSION_ID/status" -H 'Content-Type: application/json' --data '{"status":"release_candidate"}' >/dev/null
management_curl -fsS -X POST "$API_URL/api/agents/$AGENT_ID/publish" -H 'Content-Type: application/json' --data "{\"version\":\"$VERSION_ID\"}" >/dev/null

unauthorized=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/public/agents/$AGENT_ID/run" -H 'Content-Type: application/json' --data '{"input":{"topic":"AI"},"stream":false}')
test "$unauthorized" = "401"
invalid=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/public/agents/$AGENT_ID/run" -H "X-API-Key: $api_key" -H 'Content-Type: application/json' --data '{"input":{},"stream":false}')
test "$invalid" = "422"

result=$(curl -fsS --max-time 300 -X POST "$API_URL/api/public/agents/$AGENT_ID/stream" -H "X-API-Key: $api_key" -H 'Content-Type: application/json' --data '{"input":{"topic":"PHASE10_STREAM"},"stream":false,"session_id":"phase10-stream"}')
printf '%s' "$result" | python3 -c '
import json,sys
frames=[frame for frame in sys.stdin.read().split("\n\n") if frame.strip() and not frame.startswith(":")]
names=[]; events=[]
for frame in frames:
    names.extend(line[7:] for line in frame.splitlines() if line.startswith("event: "))
    data="\n".join(line[5:].lstrip() for line in frame.splitlines() if line.startswith("data:"))
    if data: events.append(json.loads(data))
assert events[0]["event"]=="start"
assert any(event["event"]=="token" and event.get("text") for event in events)
assert any(event["event"]=="trace" for event in events)
assert events[-1]["event"]=="end" and events[-1]["status"]=="success"
assert isinstance(events[-1]["result"].get("summary"), str) and events[-1]["result"]["summary"]
assert isinstance(events[-1]["result"].get("recommendations"), list)
assert names[-1]=="end"
'

sync_result=$(curl -fsS --max-time 300 -X POST "$API_URL/api/public/agents/$AGENT_ID/run" -H "X-API-Key: $api_key" -H 'Content-Type: application/json' --data '{"input":{"topic":"PHASE10_SYNC"},"stream":false,"session_id":"phase10-sync"}')
printf '%s' "$sync_result" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["agent_id"]=="phase2-public-agent"; assert value["status"]=="success"; assert isinstance(value["result"].get("summary"),str) and value["result"]["summary"]; assert isinstance(value["result"].get("recommendations"),list); assert [item["stage"] for item in value["trace"]]==["schema_input","hermes_runtime","schema_output"]'

publication=$(curl -fsS "$API_URL/api/agents/$AGENT_ID/publication")
printf '%s' "$publication" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["status"]=="published"; assert value["api_enabled"] is True; assert value["response_mode"]=="stream"; assert value["call_count"]==2; assert value["last_called_at"]; assert "api_key" not in value'
expected_hash=$(printf '%s' "$api_key" | sha256sum | cut -d' ' -f1)
stored_hash=$($COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT api_key_hash FROM agent_publications WHERE agent_id = '$AGENT_ID'")
test "$stored_hash" = "$expected_hash"
test "$stored_hash" != "$api_key"
db_contract=$($COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT model || '|' || model_adapter || '|' || api_enabled::text || '|' || prompt_template FROM agents WHERE id = '$AGENT_ID'")
test "$db_contract" = "$MODEL_ID|$MODEL_ADAPTER|true|OUTPUT_JSON_OK topic={{topic}}"

locked_configuration=$(management_curl -sS -o /dev/null -w '%{http_code}' -X PUT "$API_URL/api/agents/$AGENT_ID/configuration" -H 'Content-Type: application/json' --data "{\"system_prompt\":\"Published versions are immutable.\",\"model\":\"$MODEL_ID\",\"prompt_template\":\"{{topic}}\",\"model_adapter\":\"$MODEL_ADAPTER\",\"model_config\":{}}")
test "$locked_configuration" = "409"
publication_after_lock_check=$(curl -fsS "$API_URL/api/agents/$AGENT_ID/publication")
printf '%s' "$publication_after_lock_check" | python3 -c 'import json,sys; assert json.load(sys.stdin)["call_count"]==2'

disabled=$(management_curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/publication" -H 'Content-Type: application/json' --data '{"status":"disabled"}')
printf '%s' "$disabled" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["status"]=="disabled"; assert value["api_enabled"] is False'
disabled_call=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/public/agents/$AGENT_ID/run" -H "X-API-Key: $api_key" -H 'Content-Type: application/json' --data '{"input":{"topic":"DISABLED"},"stream":false}')
test "$disabled_call" = "404"
stored_api_enabled=$($COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT api_enabled::text FROM agents WHERE id = '$AGENT_ID'")
test "$stored_api_enabled" = "false"

echo "Phase 10 Agent Schema, Prompt Builder, Model Adapter, API Gateway, and SSE validation passed"
