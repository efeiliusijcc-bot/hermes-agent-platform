#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
API_URL=${API_URL:-http://${AGENT_API_TEST_HOST:-127.0.0.1}:${PHASE4_API_PORT:-38488}}
PROJECT_NAME=${HERMES_COMPOSE_PROJECT_NAME:-hermes-agent-phase4-verify}
COMPOSE_FILES=${HERMES_COMPOSE_FILES:-"-f $PROJECT_ROOT/docker-compose.yml -f $PROJECT_ROOT/docker-compose.phase4.verify.yml"}
COMPOSE="docker compose -p $PROJECT_NAME $COMPOSE_FILES"
AGENT_ID=${PHASE4_AGENT_ID:-phase4-production-agent}
CLIENT_NAME=${PHASE4_CLIENT_NAME:-phase4-contract-client}
SKILL_ID=knowledge-analysis
MCP_ID=phase4-filesystem-mcp
TMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/hermes-phase4.XXXXXX")
CLIENT_KEY_FILE="$TMP_ROOT/client.key"
LEGACY_KEY_FILE="$TMP_ROOT/legacy.key"
RESPONSE_FILE="$TMP_ROOT/response.json"

stage() {
  printf '[phase4] %s\n' "$1"
}

reset_resources() {
  if [ -n "${LIMITED_CLIENT_ID:-}" ]; then
    curl -sS -o /dev/null -X DELETE "$API_URL/api/api-clients/$LIMITED_CLIENT_ID" || true
  fi
  if [ -n "${CLIENT_ID:-}" ]; then
    curl -sS -o /dev/null -X DELETE "$API_URL/api/api-clients/$CLIENT_ID" || true
  fi
  curl -sS -o /dev/null -X DELETE "$API_URL/api/agents/$AGENT_ID" || true
  curl -sS -o /dev/null -X DELETE "$API_URL/api/mcp-servers/$MCP_ID" || true
}

cleanup() {
  reset_resources
  rm -rf "$TMP_ROOT"
}
trap cleanup EXIT HUP INT TERM

assert_code() {
  expected=$1
  shift
  actual=$(curl -sS -o "$RESPONSE_FILE" -w '%{http_code}' "$@")
  if [ "$actual" != "$expected" ]; then
    printf '[phase4] expected HTTP %s, received %s\n' "$expected" "$actual" >&2
    return 1
  fi
}

public_call() {
  key_file=$1
  payload=$2
  curl -fsS -X POST "$API_URL/api/public/agents/$AGENT_ID/run" \
    -H "X-API-Key: $(tr -d '\r\n' < "$key_file")" \
    -H 'Content-Type: application/json' --data "$payload"
}

stage "checking platform health"
curl -fsS "$API_URL/health" |
  python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["status"]=="ok"'

reset_resources
stage "creating draft Agent and checking lifecycle gates"
curl -fsS -X POST "$API_URL/api/agents" -H 'Content-Type: application/json' --data "{
  \"id\":\"$AGENT_ID\",\"name\":\"Phase 4 Production Agent\",\"description\":\"v1 configuration\",
  \"role\":\"contract tester\",\"system_prompt\":\"Return valid JSON containing OUTPUT_JSON_OK.\",
  \"model\":\"phase4-contract-model\",\"model_adapter\":\"qwen\",\"prompt_template\":\"OUTPUT_JSON_OK {{topic}}\",
  \"model_config\":{\"temperature\":0},\"status\":\"draft\",\"response_mode\":\"sync\",
  \"input_schema\":{\"type\":\"object\",\"properties\":{\"topic\":{\"type\":\"string\"}},\"required\":[\"topic\"],\"additionalProperties\":false},
  \"output_schema\":{\"type\":\"object\",\"properties\":{\"summary\":{\"type\":\"string\"},\"recommendations\":{\"type\":\"array\"}},\"required\":[\"summary\",\"recommendations\"],\"additionalProperties\":false}
}" >/dev/null

# The runtime Skill files and control-plane registry are deliberately separate.
# Register the bundled contract Skill if this isolated database is new.
if ! curl -fsS "$API_URL/api/skills/$SKILL_ID" >/dev/null 2>&1; then
  curl -fsS -X POST "$API_URL/api/skills" -H 'Content-Type: application/json' \
    --data "{\"id\":\"$SKILL_ID\",\"name\":\"Knowledge Analysis\",\"description\":\"Phase 4 contract Skill\",\"path\":\"$SKILL_ID\"}" >/dev/null
fi

# Illegal lifecycle skip and production invocation before publication are rejected.
assert_code 409 -X PATCH "$API_URL/api/agents/$AGENT_ID/lifecycle" \
  -H 'Content-Type: application/json' --data '{"status":"published"}'
assert_code 404 -X POST "$API_URL/api/public/agents/$AGENT_ID/run" \
  -H 'X-API-Key: not-a-key' -H 'Content-Type: application/json' --data '{"input":{"topic":"blocked"}}'

# Health gates publication. The contract stack uses the deterministic model stub.
stage "checking Agent health and internal testing execution"
curl -fsS "$API_URL/api/agents/$AGENT_ID/health" |
  python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["agent_id"]=="phase4-production-agent"; assert v["status"] in ("healthy","degraded") and set(v["checks"]) >= {"model","skills","mcp"}'
curl -fsS -X PATCH "$API_URL/api/agents/$AGENT_ID/lifecycle" \
  -H 'Content-Type: application/json' --data '{"status":"testing"}' >/dev/null
# Testing allows internal execution but still rejects public invocation.
curl -fsS -X POST "$API_URL/api/agents/$AGENT_ID/run" -H 'Content-Type: application/json' \
  --data '{"input":"{\"topic\":\"internal-testing\"}"}' |
  python3 -c 'import json,sys; assert json.load(sys.stdin)["status"]=="succeeded"'
assert_code 404 -X POST "$API_URL/api/public/agents/$AGENT_ID/run" \
  -H 'X-API-Key: not-a-key' -H 'Content-Type: application/json' --data '{"input":{"topic":"blocked"}}'

# Snapshot and rollback must include real Skill and MCP bindings.
stage "binding Skill and MCP resources"
curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/skills/$SKILL_ID" >/dev/null
curl -fsS -X POST "$API_URL/api/mcp-servers" -H 'Content-Type: application/json' --data "{
  \"id\":\"$MCP_ID\",\"name\":\"Phase 4 Filesystem MCP\",\"endpoint\":\"http://mcp-gateway:8090/mcp\",
  \"config\":{\"kind\":\"filesystem\",\"read_only\":true},\"permission\":\"read_only\"
}" >/dev/null
curl -fsS -X POST "$API_URL/api/mcp-servers/$MCP_ID/test" |
  python3 -c 'import json,sys; assert json.load(sys.stdin)["status"]=="online"'
curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/mcp-servers/$MCP_ID" >/dev/null

# Snapshot v1, publish it, then later prove rollback restores this exact configuration.
stage "snapshotting and publishing v1"
curl -fsS -X POST "$API_URL/api/agents/$AGENT_ID/versions" \
  -H 'Content-Type: application/json' --data '{"version":"v1.0","description":"baseline"}' |
  python3 -c 'import json,sys; v=json.load(sys.stdin); s=v["snapshot"]; assert v["version"]=="v1.0" and s["prompt"]["system_prompt"].startswith("Return valid JSON"); assert s["skill_ids"]==["knowledge-analysis"] and s["mcp_ids"]==["phase4-filesystem-mcp"]'

# Legacy one-Agent key remains accepted during migration.
curl -fsS -X POST "$API_URL/api/agents/$AGENT_ID/publication/api-key" |
  python3 -c 'import json,sys,pathlib; v=json.load(sys.stdin); assert v["api_key"].startswith("hap_"); pathlib.Path(sys.argv[1]).write_text(v["api_key"])' "$LEGACY_KEY_FILE"
curl -fsS -X POST "$API_URL/api/agents/$AGENT_ID/publish" \
  -H 'Content-Type: application/json' --data '{"version":"v1.0"}' >/dev/null

# The compatibility endpoint must create a standard active Client, Key, and
# invoke binding. Publication Hash/Prefix alone is never an authentication path.
legacy_hash=$(sha256sum "$LEGACY_KEY_FILE" | awk '{print $1}')
legacy_auth=$($COMPOSE exec -T postgres psql -At -F '|' -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -v ON_ERROR_STOP=1 -c "SELECT client.id, key.id FROM api_clients client JOIN api_keys key ON key.client_id=client.id JOIN agent_api_clients binding ON binding.client_id=client.id AND binding.agent_id='$AGENT_ID' WHERE client.name='legacy-$AGENT_ID' AND client.status='active' AND key.key_hash='$legacy_hash' AND key.status='active' AND binding.permission='invoke'")
LEGACY_CLIENT_ID=$(printf '%s' "$legacy_auth" | awk -F '|' 'NF==2 {print $1}')
LEGACY_KEY_ID=$(printf '%s' "$legacy_auth" | awk -F '|' 'NF==2 {print $2}')
test -n "$LEGACY_CLIENT_ID" && test -n "$LEGACY_KEY_ID"

# Client Key plaintext is returned only on creation; list responses must expose prefix only.
stage "creating Client Key and checking secret handling"
client=$(curl -fsS -X POST "$API_URL/api/api-clients" -H 'Content-Type: application/json' \
  --data "{\"name\":\"$CLIENT_NAME\",\"owner\":\"phase4-test\",\"rate_limit_per_minute\":60}")
CLIENT_ID=$(printf '%s' "$client" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
key_secret=$(curl -fsS -X POST "$API_URL/api/api-clients/$CLIENT_ID/keys" \
  -H 'Content-Type: application/json' --data '{"name":"contract-key"}')
KEY_ID=$(printf '%s' "$key_secret" | python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["api_key"].startswith("hap_"); print(v["id"])')
printf '%s' "$key_secret" | python3 -c 'import json,sys,pathlib; pathlib.Path(sys.argv[1]).write_text(json.load(sys.stdin)["api_key"])' "$CLIENT_KEY_FILE"
curl -fsS "$API_URL/api/api-clients/$CLIENT_ID/keys" |
  python3 -c 'import json,sys; v=json.load(sys.stdin); assert len(v)==1 and "api_key" not in v[0] and v[0]["prefix"].startswith("hap_")'

# Before invoke binding, a valid Client Key is forbidden; after binding it succeeds.
stage "checking Client authorization and sync invocation"
assert_code 403 -X POST "$API_URL/api/public/agents/$AGENT_ID/run" \
  -H "X-API-Key: $(tr -d '\r\n' < "$CLIENT_KEY_FILE")" -H 'Content-Type: application/json' \
  --data '{"input":{"topic":"not-bound"}}'
curl -fsS -X POST "$API_URL/api/api-clients/$CLIENT_ID/agents" \
  -H 'Content-Type: application/json' --data "{\"agent_id\":\"$AGENT_ID\",\"permission\":\"invoke\"}" |
  python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["permission"]=="invoke"'

public_call "$CLIENT_KEY_FILE" '{"input":{"topic":"client-sync"}}' |
  python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["status"]=="success" and v["result"]["summary"].startswith("OUTPUT_JSON_OK")'
public_call "$LEGACY_KEY_FILE" '{"input":{"topic":"legacy-sync"}}' |
  python3 -c 'import json,sys; assert json.load(sys.stdin)["status"]=="success"'
# Live published configuration and bindings are immutable until suspension.
assert_code 409 -X PUT "$API_URL/api/agents/$AGENT_ID/configuration" -H 'Content-Type: application/json' --data '{
  "system_prompt":"must be rejected","model":"changed-model","model_adapter":"qwen",
  "prompt_template":"OUTPUT_JSON_OK {{topic}}","model_config":{}
}'
assert_code 409 -X DELETE "$API_URL/api/agents/$AGENT_ID/skills/$SKILL_ID"

# Streaming completion must also produce one successful audit/metric observation.
stage "checking SSE invocation, audit, and metrics"
curl -fsS -N -X POST "$API_URL/api/public/agents/$AGENT_ID/stream" \
  -H "X-API-Key: $(tr -d '\r\n' < "$CLIENT_KEY_FILE")" -H 'Content-Type: application/json' \
  --data '{"input":{"topic":"client-stream"}}' > "$TMP_ROOT/stream.sse"
grep -q '^event: start' "$TMP_ROOT/stream.sse"
grep -q '^event: end' "$TMP_ROOT/stream.sse"

# Failure/rejection path is audited; audit contains metadata but no request input.
assert_code 422 -X POST "$API_URL/api/public/agents/$AGENT_ID/run" \
  -H "X-API-Key: $(tr -d '\r\n' < "$CLIENT_KEY_FILE")" -H 'Content-Type: application/json' \
  --data '{"input":{}}'
curl -fsS "$API_URL/api/audit-logs?agent_id=$AGENT_ID&limit=20" |
  python3 -c 'import json,sys; v=json.load(sys.stdin); assert len(v)>=4; assert {x["status"] for x in v} >= {"succeeded","rejected"}; assert all("input" not in x for x in v); assert all(x["latency_ms"] >= 0 and x["mcp_call_count"] >= 0 for x in v); assert any(x["status"]=="succeeded" and isinstance(x["token_usage"],int) and x["token_usage"]>0 for x in v); assert any(x["client_id"]==sys.argv[1] and x["api_key_id"]==sys.argv[2] and x["status"]=="succeeded" for x in v)' "$LEGACY_CLIENT_ID" "$LEGACY_KEY_ID"
curl -fsS "$API_URL/api/metrics/agents/$AGENT_ID" |
  python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["call_count"]>=4 and v["success_count"]>=3 and v["failure_count"]>=1; assert v["average_latency_ms"]>=0; assert v["mcp_call_count"]>=0; assert v["token_usage"] is None'

# Database accepts only hash/prefix; neither freshly returned plaintext key may occur in storage.
stage "checking database key hashing"
client_hash=$(sha256sum "$CLIENT_KEY_FILE" | awk '{print $1}')
$COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
  -c "SELECT count(*) FROM api_keys WHERE id='$KEY_ID'::uuid AND length(key_hash)=64 AND key_hash='$client_hash' AND prefix LIKE 'hap_%'" | grep -qx 1
$COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
  -c "SELECT count(*) FROM api_keys WHERE id='$LEGACY_KEY_ID'::uuid AND client_id='$LEGACY_CLIENT_ID'::uuid AND key_hash='$legacy_hash' AND length(key_hash)=64" | grep -qx 1
$COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c '\d api_keys' | grep -q 'key_hash'
if $COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c '\d api_keys' | grep -Eq '(^|[|[:space:]])api_key([|[:space:]]|$)'; then exit 1; fi

# Revoke and suspend both deny invocation. A low-limit client proves 429 separately.
stage "checking revocation and rate limiting"

# Client suspension rejects an otherwise active, bound Key; reactivation restores it.
curl -fsS -X PATCH "$API_URL/api/api-clients/$CLIENT_ID" -H 'Content-Type: application/json' \
  --data '{"status":"suspended"}' >/dev/null
assert_code 401 -X POST "$API_URL/api/public/agents/$AGENT_ID/run" \
  -H "X-API-Key: $(tr -d '\r\n' < "$CLIENT_KEY_FILE")" -H 'Content-Type: application/json' \
  --data '{"input":{"topic":"client-suspended"}}'
curl -fsS -X PATCH "$API_URL/api/api-clients/$CLIENT_ID" -H 'Content-Type: application/json' \
  --data '{"status":"active"}' >/dev/null
public_call "$CLIENT_KEY_FILE" '{"input":{"topic":"client-reactivated"}}' >/dev/null

curl -fsS -X PATCH "$API_URL/api/api-clients/$CLIENT_ID/keys/$KEY_ID" \
  -H 'Content-Type: application/json' --data '{"status":"revoked"}' >/dev/null
assert_code 401 -X POST "$API_URL/api/public/agents/$AGENT_ID/run" \
  -H "X-API-Key: $(tr -d '\r\n' < "$CLIENT_KEY_FILE")" -H 'Content-Type: application/json' \
  --data '{"input":{"topic":"revoked"}}'

limited=$(curl -fsS -X POST "$API_URL/api/api-clients" -H 'Content-Type: application/json' \
  --data '{"name":"phase4-rate-limit-client","owner":"phase4-test","rate_limit_per_minute":1}')
LIMITED_CLIENT_ID=$(printf '%s' "$limited" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
limited_key=$(curl -fsS -X POST "$API_URL/api/api-clients/$LIMITED_CLIENT_ID/keys" -H 'Content-Type: application/json' --data '{"name":"limited"}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["api_key"])')
curl -fsS -X POST "$API_URL/api/api-clients/$LIMITED_CLIENT_ID/agents" -H 'Content-Type: application/json' \
  --data "{\"agent_id\":\"$AGENT_ID\",\"permission\":\"invoke\"}" >/dev/null
curl -fsS -X POST "$API_URL/api/public/agents/$AGENT_ID/run" -H "X-API-Key: $limited_key" \
  -H 'Content-Type: application/json' --data '{"input":{"topic":"rate-1"}}' >/dev/null
assert_code 429 -X POST "$API_URL/api/public/agents/$AGENT_ID/run" -H "X-API-Key: $limited_key" \
  -H 'Content-Type: application/json' --data '{"input":{"topic":"rate-2"}}'
curl -sS -o /dev/null -X DELETE "$API_URL/api/api-clients/$LIMITED_CLIENT_ID" || true

# Suspend before changing production configuration, snapshot v2, then roll back
# and prove prompt/model/bindings are v1 again.
stage "checking suspension, version rollback, and binding restore"
curl -fsS -X PATCH "$API_URL/api/agents/$AGENT_ID/lifecycle" \
  -H 'Content-Type: application/json' --data '{"status":"suspended"}' >/dev/null
assert_code 409 -X POST "$API_URL/api/agents/$AGENT_ID/run" -H 'Content-Type: application/json' \
  --data '{"input":"{\"topic\":\"suspended-internal\"}"}'
assert_code 404 -X POST "$API_URL/api/public/agents/$AGENT_ID/run" \
  -H "X-API-Key: $(tr -d '\r\n' < "$LEGACY_KEY_FILE")" -H 'Content-Type: application/json' \
  --data '{"input":{"topic":"suspended-public"}}'
# Remove the bindings and prove rollback reconstructs them from v1.
curl -fsS -o /dev/null -X DELETE "$API_URL/api/agents/$AGENT_ID/skills/$SKILL_ID"
curl -fsS -o /dev/null -X DELETE "$API_URL/api/agents/$AGENT_ID/mcp-servers/$MCP_ID"
curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/configuration" -H 'Content-Type: application/json' --data '{
  "system_prompt":"changed prompt","model":"changed-model","model_adapter":"qwen",
  "prompt_template":"OUTPUT_JSON_OK {{topic}}","model_config":{"temperature":1}
}' >/dev/null
curl -fsS -X POST "$API_URL/api/agents/$AGENT_ID/versions" -H 'Content-Type: application/json' \
  --data '{"version":"v2.0","description":"changed"}' >/dev/null
curl -fsS -X POST "$API_URL/api/agents/$AGENT_ID/versions/v1.0/rollback" |
  python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["status"]=="published" and v["id"]=="phase4-production-agent"'
curl -fsS "$API_URL/api/agents/$AGENT_ID/health" |
  python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["status"]=="healthy" and all(x["status"]=="healthy" for x in v["checks"].values())'
curl -fsS "$API_URL/api/agents/$AGENT_ID" |
  python3 -c 'import json,sys; v=json.load(sys.stdin); assert v["system_prompt"].startswith("Return valid JSON") and v["model"]=="phase4-contract-model" and v["model_config"]=={"temperature":0}'
curl -fsS "$API_URL/api/agents/$AGENT_ID/skills" |
  python3 -c 'import json,sys; assert [x["id"] for x in json.load(sys.stdin)]==["knowledge-analysis"]'
curl -fsS "$API_URL/api/agents/$AGENT_ID/mcp-servers" |
  python3 -c 'import json,sys; assert [x["id"] for x in json.load(sys.stdin)]==["phase4-filesystem-mcp"]'
$COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
  -c "SELECT api.api_version || '|' || schema.version || '|' || api.status || '|' || schema.status FROM agent_api_versions api JOIN agent_schema_versions schema ON schema.id=api.schema_version_id WHERE api.agent_id='$AGENT_ID' AND api.api_version='v1'" | grep -qx 'v1|v1|published|published'

# Rollback must also restore the Phase 2 publication gate used by the public
# route; disabling it before rollback proves the restoration is not cosmetic.
curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/publication" -H 'Content-Type: application/json' \
  --data '{"status":"disabled"}' >/dev/null
assert_code 404 -X POST "$API_URL/api/public/agents/$AGENT_ID/run" \
  -H "X-API-Key: $(tr -d '\r\n' < "$LEGACY_KEY_FILE")" -H 'Content-Type: application/json' \
  --data '{"input":{"topic":"publication-disabled"}}'
curl -fsS -X POST "$API_URL/api/agents/$AGENT_ID/versions/v1.0/rollback" >/dev/null
public_call "$LEGACY_KEY_FILE" '{"input":{"topic":"publication-restored"}}' >/dev/null

# Archived is terminal and rejects every invocation and lifecycle rollback.
stage "checking terminal archive lifecycle"
curl -fsS -X PATCH "$API_URL/api/agents/$AGENT_ID/lifecycle" -H 'Content-Type: application/json' \
  --data '{"status":"suspended"}' >/dev/null
curl -fsS -X PATCH "$API_URL/api/agents/$AGENT_ID/lifecycle" -H 'Content-Type: application/json' \
  --data '{"status":"archived"}' >/dev/null
assert_code 409 -X PATCH "$API_URL/api/agents/$AGENT_ID/lifecycle" -H 'Content-Type: application/json' \
  --data '{"status":"testing"}'
assert_code 409 -X POST "$API_URL/api/agents/$AGENT_ID/run" -H 'Content-Type: application/json' \
  --data '{"input":"{\"topic\":\"archived\"}"}'

echo "Phase 4 production Agent lifecycle, Client authorization, audit, metrics, health, version, and rollback validation passed"
