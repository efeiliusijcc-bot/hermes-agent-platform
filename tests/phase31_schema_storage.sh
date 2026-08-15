#!/usr/bin/env sh
set -eu

API_URL=${API_URL:-http://127.0.0.1:38188}
AGENT_ID=${AGENT_ID:-phase31-schema-agent}
API_KEY_FILE=${API_KEY_FILE:?API_KEY_FILE is required}
RESPONSE_FILE=${RESPONSE_FILE:?RESPONSE_FILE is required}

cleanup() {
  curl -fsS -X DELETE "$API_URL/api/agents/$AGENT_ID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cleanup
curl -fsS -X POST "$API_URL/api/agents" -H 'Content-Type: application/json' -d "{
  \"id\":\"$AGENT_ID\",\"name\":\"Phase 3.1 Schema Agent\",\"role\":\"tester\",
  \"system_prompt\":\"Return valid JSON containing OUTPUT_JSON_OK.\",\"status\":\"active\",
  \"model\":\"phase31-model\",\"model_adapter\":\"qwen\",\"prompt_template\":\"OUTPUT_JSON_OK {{topic}}\",
  \"input_schema\":{\"type\":\"object\",\"properties\":{\"topic\":{\"type\":\"string\"}},\"required\":[\"topic\"],\"additionalProperties\":false},
  \"output_schema\":{\"type\":\"object\",\"properties\":{\"summary\":{\"type\":\"string\"},\"recommendations\":{\"type\":\"array\"}},\"required\":[\"summary\",\"recommendations\"],\"additionalProperties\":false}
}" >/dev/null

curl -fsS -X POST "$API_URL/api/agents/$AGENT_ID/publication/api-key" |
  python3 -c 'import json,sys,pathlib; pathlib.Path(sys.argv[1]).write_text(json.load(sys.stdin)["api_key"])' "$API_KEY_FILE"
curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/publication" -H 'Content-Type: application/json' -d '{"status":"published"}' >/dev/null

curl -fsS "$API_URL/api/agents/$AGENT_ID/schema-versions" |
  python3 -c 'import json,sys; v=json.load(sys.stdin); assert len(v)==1 and v[0]["version"]=="v1" and v[0]["status"]=="published"'
curl -fsS "$API_URL/api/agents/$AGENT_ID/api-versions" |
  python3 -c 'import json,sys; v=json.load(sys.stdin); assert len(v)==1 and v[0]["api_version"]=="v1" and v[0]["schema_version"]["version"]=="v1"'

code=$(curl -sS -o "$RESPONSE_FILE" -w '%{http_code}' -X POST "$API_URL/api/v1/agents/$AGENT_ID/run" \
  -H "X-API-Key: $(tr -d '\n' < "$API_KEY_FILE")" -H 'Content-Type: application/json' -d '{"input":{}}')
test "$code" = 422

call_api() {
  version=$1
  payload=$2
  curl -fsS -X POST "$API_URL/api/$version/agents/$AGENT_ID/run" \
    -H "X-API-Key: $(tr -d '\n' < "$API_KEY_FILE")" -H 'Content-Type: application/json' -d "$payload"
}

call_api v1 '{"input":{"topic":"legacy"}}' |
  python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["status"]=="success" and v["result"]=={"summary":"OUTPUT_JSON_OK:phase31-model","recommendations":[]}'

curl -fsS -X POST "$API_URL/api/agents/$AGENT_ID/schema-versions" -H 'Content-Type: application/json' -d '{
  "version":"v2",
  "input_schema":{"type":"object","properties":{"topic":{"type":"string"},"industry":{"type":"string"}},"required":["topic","industry"],"additionalProperties":false},
  "output_schema":{"type":"object","properties":{"summary":{"type":"string"},"recommendations":{"type":"array"}},"required":["summary","recommendations"],"additionalProperties":false}
}' >/dev/null
curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/schema-versions/v2/status" -H 'Content-Type: application/json' -d '{"status":"testing"}' >/dev/null
curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/schema-versions/v2/status" -H 'Content-Type: application/json' -d '{"status":"published"}' >/dev/null
curl -fsS -X POST "$API_URL/api/agents/$AGENT_ID/api-versions" -H 'Content-Type: application/json' -d '{"api_version":"v2","schema_version":"v2"}' >/dev/null
curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/api-versions/v2/status" -H 'Content-Type: application/json' -d '{"status":"testing"}' >/dev/null
curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/api-versions/v2/status" -H 'Content-Type: application/json' -d '{"status":"published"}' >/dev/null

call_api v2 '{"input":{"topic":"current","industry":"software"}}' |
  python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["status"]=="success" and v["result"]=={"summary":"OUTPUT_JSON_OK:phase31-model","recommendations":[]}'
curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/api-versions/v1/status" -H 'Content-Type: application/json' -d '{"status":"deprecated"}' >/dev/null
call_api v1 '{"input":{"topic":"legacy-after-deprecation"}}' |
  python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["status"]=="success"'
curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/api-versions/v1/status" -H 'Content-Type: application/json' -d '{"status":"disabled"}' >/dev/null
code=$(curl -sS -o "$RESPONSE_FILE" -w '%{http_code}' -X POST "$API_URL/api/v1/agents/$AGENT_ID/run" \
  -H "X-API-Key: $(tr -d '\n' < "$API_KEY_FILE")" -H 'Content-Type: application/json' -d '{"input":{"topic":"disabled"}}')
test "$code" = 404

curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/memory/shared/short-term/facts" -H 'Content-Type: application/json' -d '{"value":{"marker":"phase31"}}' >/dev/null
curl -fsS "$API_URL/api/agents/$AGENT_ID/memory/shared/short-term/facts" |
  python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["namespace"].endswith("/shared/short-term") and v["value"]["marker"]=="phase31"'
curl -fsS -X DELETE "$API_URL/api/agents/$AGENT_ID/memory/shared/short-term/facts" >/dev/null

echo "Phase 3.1 Schema version, API binding, and Memory Provider validation passed"
