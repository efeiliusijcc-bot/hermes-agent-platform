#!/usr/bin/env sh
set -eu

PROJECT_ROOT=${PROJECT_ROOT:-/opt/hermes-agent-platform}
VERIFY_ROOT=${MULTIDATABASE_VERIFY_ROOT:-/opt/agent-multidb-verify}
VERIFY_IMAGE=${MULTIDATABASE_VERIFY_IMAGE:-agent-platform/database-mcp:multidb-verify}
VERIFY_CONTAINER=${MULTIDATABASE_VERIFY_CONTAINER:-agent-database-mcp-verify}
VERIFY_PORT=${MULTIDATABASE_VERIFY_PORT:-28091}

test ! -e "$VERIFY_ROOT" || {
  echo "Verification root already exists: $VERIFY_ROOT" >&2
  exit 1
}
mkdir -p "$VERIFY_ROOT"

docker run --rm --user 0:0 \
  -v "$VERIFY_ROOT:/data/databases" \
  --entrypoint python "$VERIFY_IMAGE" -c '
import sqlite3
connection = sqlite3.connect("/data/databases/demo.db")
connection.execute("create table reports(id integer, title text)")
connection.execute("insert into reports values(?, ?)", (1, "offline-ready"))
connection.commit()
connection.close()
'

cd "$PROJECT_ROOT"
set -a
. ./.env
set +a
network=$(docker inspect hermes-agent-platform-postgres-1 \
  --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' | sed -n '1p')
test -n "$network"
docker rm -f "$VERIFY_CONTAINER" >/dev/null 2>&1 || true
docker run -d \
  --name "$VERIFY_CONTAINER" \
  --network "$network" \
  -v "$VERIFY_ROOT:/data/databases:ro" \
  -e MCP_GATEWAY_SIGNING_KEY \
  -e MODEL_REGISTRY_ENCRYPTION_KEY \
  -e POSTGRES_HOST=postgres \
  -e POSTGRES_PORT=5432 \
  -e POSTGRES_DB \
  -e POSTGRES_USER \
  -e POSTGRES_PASSWORD \
  -e REDIS_HOST=redis \
  -e REDIS_PORT=6379 \
  -e REDIS_DB \
  -e REDIS_PASSWORD \
  -e DATABASE_MCP_SQLITE_ROOT=/data/databases \
  "$VERIFY_IMAGE" >/dev/null

ready=false
attempt=0
while [ "$attempt" -lt 20 ]; do
  if docker exec "$VERIFY_CONTAINER" python -c \
    'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8091/health", timeout=2).read()' \
    >/dev/null 2>&1; then
    ready=true
    break
  fi
  attempt=$((attempt + 1))
  sleep 1
done
test "$ready" = true || {
  docker logs --tail 80 "$VERIFY_CONTAINER" >&2
  exit 1
}

docker exec "$VERIFY_CONTAINER" python -c '
import json
import urllib.request
payload = {
    "endpoint": {"database_type": "sqlite", "database_file": "demo.db", "maintenance_database": "main"},
    "credential": {"username": "", "password": ""},
}
request = urllib.request.Request(
    "http://127.0.0.1:8091/internal/admin/test",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(request, timeout=30) as response:
    print(response.read().decode())
' > "$VERIFY_ROOT/sqlite-discovery.json"
python3 - "$VERIFY_ROOT/sqlite-discovery.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    value = json.load(stream)
assert value["status"] == "READY", value
assert value["database_type"] == "sqlite", value
objects = value["databases"][0]["schemas"][0]["tables"]
assert any(item["name"] == "reports" for item in objects), objects
print("SQLite Database MCP discovery passed")
PY

docker inspect --format '{{.Name}} {{.State.Status}} {{.Config.Image}}' "$VERIFY_CONTAINER"
