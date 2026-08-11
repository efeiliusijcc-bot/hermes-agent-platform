#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
API_URL="http://${AGENT_API_TEST_HOST:-127.0.0.1}:${AGENT_API_PORT:-18088}"
COMPOSE="docker compose -p hermes-agent-platform -f $PROJECT_ROOT/docker-compose.yml"
AGENT_ID="phase7-knowledge-agent"
SOURCE_ID="phase7-company-docs"
FIXTURE="$PROJECT_ROOT/tests/fixtures/knowledge/test.md"

curl -sS -o /dev/null -X DELETE "$API_URL/api/agents/$AGENT_ID" || true
curl -sS -o /dev/null -X DELETE "$API_URL/api/knowledge-sources/$SOURCE_ID" || true

$COMPOSE exec -T knowledge-service python - < "$PROJECT_ROOT/tests/phase7_parser_formats.py"

source=$(curl -fsS -X POST "$API_URL/api/knowledge-sources" \
  -H 'Content-Type: application/json' \
  --data '{
    "id": "phase7-company-docs",
    "name": "Phase 7 Company Documents",
    "description": "Phase 7 pgvector retrieval validation",
    "status": "active"
  }')
printf '%s' "$source" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["id"]=="phase7-company-docs"; assert value["config"]=={"embedding_model":"hash-ngram-v1","dimensions":384}; assert value["status"]=="active"'

duplicate_source_status=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$API_URL/api/knowledge-sources" \
  -H 'Content-Type: application/json' \
  --data '{"id":"phase7-company-docs","name":"duplicate"}')
test "$duplicate_source_status" = "409"

curl -fsS -X POST "$API_URL/api/agents" \
  -H 'Content-Type: application/json' \
  --data '{
    "id": "phase7-knowledge-agent",
    "name": "Phase 7 Knowledge Agent",
    "role": "企业知识检索员",
    "system_prompt": "只能根据 Retrieved Knowledge 中实际召回的内容总结；必须保留文档中的验收标记，不得编造。",
    "model_config": {"model": "external-openai-compatible"},
    "status": "active"
  }' >/dev/null

binding=$(curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/knowledge-sources/$SOURCE_ID")
printf '%s' "$binding" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value=={"agent_id":"phase7-knowledge-agent","source_ids":["phase7-company-docs"]}'
binding_repeat=$(curl -fsS -X PUT "$API_URL/api/agents/$AGENT_ID/knowledge-sources/$SOURCE_ID")
printf '%s' "$binding_repeat" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["source_ids"]==["phase7-company-docs"]'

invalid_upload_status=$(curl -sS -o /dev/null -w '%{http_code}' -X POST \
  "$API_URL/api/knowledge-sources/$SOURCE_ID/documents" \
  -F 'file=@/etc/hosts;filename=test.bin;type=application/octet-stream')
test "$invalid_upload_status" = "415"

document=$(curl -fsS -X POST "$API_URL/api/knowledge-sources/$SOURCE_ID/documents" \
  -F "file=@$FIXTURE;filename=test.md;type=text/markdown")
printf '%s' "$document" | python3 -c 'import hashlib,json,sys; value=json.load(sys.stdin); expected=hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest(); assert value["source_id"]=="phase7-company-docs"; assert value["filename"]=="test.md"; assert value["parser"]=="utf8-text"; assert value["sha256"]==expected; assert value["chunk_count"]>=1; assert value["size_bytes"]>0' "$FIXTURE"

duplicate_document_status=$(curl -sS -o /dev/null -w '%{http_code}' -X POST \
  "$API_URL/api/knowledge-sources/$SOURCE_ID/documents" \
  -F "file=@$FIXTURE;filename=test-copy.md;type=text/markdown")
test "$duplicate_document_status" = "409"

documents=$(curl -fsS "$API_URL/api/knowledge-sources/$SOURCE_ID/documents")
printf '%s' "$documents" | python3 -c 'import json,sys; values=json.load(sys.stdin); assert len(values)==1; assert values[0]["filename"]=="test.md"'

search=$(curl -fsS -X POST "$API_URL/api/knowledge-sources/$SOURCE_ID/search" \
  -H 'Content-Type: application/json' \
  --data '{"query":"北辰计划 离线知识 POLARIS_KNOWLEDGE_SIGNAL_27","top_k":3}')
printf '%s' "$search" | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["embedding_model"]=="hash-ngram-v1"; assert value["dimensions"]==384; assert value["hits"]; hit=value["hits"][0]; assert hit["source_id"]=="phase7-company-docs"; assert hit["filename"]=="test.md"; assert "POLARIS_KNOWLEDGE_SIGNAL_27" in hit["content"]; assert -1 <= hit["score"] <= 1'

chunk_count=$($COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "SELECT count(*) FROM knowledge_chunks WHERE source_id = '$SOURCE_ID' AND vector_dims(embedding) = 384")
test "$chunk_count" -ge 1
object_count=$($COMPOSE run --rm --entrypoint /bin/sh minio-init -ec '
  mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
  mc find local/knowledge/phase7-company-docs --name test.md 2>/dev/null | wc -l | tr -d " "
')
test "$object_count" = "1"

run_result=$(curl -fsS --max-time 300 -X POST "$API_URL/api/agents/$AGENT_ID/run" \
  -H 'Content-Type: application/json' \
  --data '{"session_id":"phase7-knowledge-session","input":"总结该文档，必须说明部署方式、项目结论并原样引用验收标记。"}')
printf '%s' "$run_result" | python3 -c 'import json,sys; value=json.load(sys.stdin); output=value["output"]; assert value["status"]=="succeeded"; assert "POLARIS_KNOWLEDGE_SIGNAL_27" in output; assert "116" in output'

runs=$(curl -fsS "$API_URL/api/agents/$AGENT_ID/runs")
printf '%s' "$runs" | python3 -c 'import json,sys; values=json.load(sys.stdin); details=values[0]["details"]; assert details["knowledge_loaded"]==["phase7-company-docs"]; assert details["knowledge_hits"]; assert details["knowledge_hits"][0]["source_id"]=="phase7-company-docs"; assert "POLARIS_KNOWLEDGE_SIGNAL_27" not in json.dumps(details)'

$COMPOSE logs --no-color --since=10m knowledge-service | grep -q "Knowledge document indexed: source=$SOURCE_ID"
$COMPOSE logs --no-color --since=10m agent-api | grep -q "Knowledge loaded: $SOURCE_ID"

curl -fsS -o /dev/null -X DELETE "$API_URL/api/knowledge-sources/$SOURCE_ID"
bound_after_delete=$(curl -fsS "$API_URL/api/agents/$AGENT_ID/knowledge-sources")
printf '%s' "$bound_after_delete" | python3 -c 'import json,sys; assert json.load(sys.stdin)==[]'
document_count_after=$($COMPOSE exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "SELECT count(*) FROM knowledge_documents WHERE source_id = '$SOURCE_ID'")
test "$document_count_after" = "0"
object_count_after=$($COMPOSE run --rm --entrypoint /bin/sh minio-init -ec '
  mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
  mc find local/knowledge/phase7-company-docs --name test.md 2>/dev/null | wc -l | tr -d " "
')
test "$object_count_after" = "0"

curl -fsS -o /dev/null -X DELETE "$API_URL/api/agents/$AGENT_ID"
echo "Phase 7 Knowledge service validation passed"
