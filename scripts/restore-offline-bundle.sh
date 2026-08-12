#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PROJECT_NAME=${OFFLINE_PROJECT_NAME:-hermes-agent-platform}
TARGET_API_PORT=${OFFLINE_AGENT_API_PORT:-18088}
TARGET_FRONTEND_PORT=${OFFLINE_FRONTEND_PORT:-18089}
TARGET_INTERNAL_NETWORK=${OFFLINE_INTERNAL_NETWORK_NAME:-hermes-agent-platform-internal}
TARGET_EDGE_NETWORK=${OFFLINE_EDGE_NETWORK_NAME:-hermes-agent-platform-edge}

test -f "$PROJECT_ROOT/.env" || {
  echo "Offline bundle is missing .env" >&2
  exit 1
}
test -f "$PROJECT_ROOT/images.tar" || {
  echo "Offline bundle is missing images.tar" >&2
  exit 1
}
test -f "$PROJECT_ROOT/SHA256SUMS" || {
  echo "Offline bundle is missing SHA256SUMS" >&2
  exit 1
}

(
  cd "$PROJECT_ROOT"
  sha256sum -c SHA256SUMS >/dev/null
)

if [ -d "$PROJECT_ROOT/data" ] && find "$PROJECT_ROOT/data" -mindepth 1 -print -quit | grep -q .; then
  echo "Restore target data directory is not empty: $PROJECT_ROOT/data" >&2
  exit 1
fi

set -a
. "$PROJECT_ROOT/.env"
set +a
HERMES_COMPOSE_PROJECT_NAME=$PROJECT_NAME
HERMES_INTERNAL_NETWORK_NAME=$TARGET_INTERNAL_NETWORK
HERMES_EDGE_NETWORK_NAME=$TARGET_EDGE_NETWORK
AGENT_API_PORT=$TARGET_API_PORT
FRONTEND_PORT=$TARGET_FRONTEND_PORT
export HERMES_COMPOSE_PROJECT_NAME HERMES_INTERNAL_NETWORK_NAME HERMES_EDGE_NETWORK_NAME AGENT_API_PORT FRONTEND_PORT

COMPOSE="docker compose -p $PROJECT_NAME -f $PROJECT_ROOT/docker-compose.yml"

docker load --input "$PROJECT_ROOT/images.tar" >/dev/null
while IFS= read -r image_ref; do
  test -z "$image_ref" || docker image inspect "$image_ref" >/dev/null
done < "$PROJECT_ROOT/OFFLINE_IMAGES.txt"

"$PROJECT_ROOT/scripts/prepare-data-dirs.sh"
cp "$PROJECT_ROOT/offline-data/redis/dump.rdb" "$PROJECT_ROOT/data/redis/dump.rdb"
for data_name in hermes hermes-workspace mcp-files; do
  if [ -d "$PROJECT_ROOT/offline-data/$data_name" ]; then
    cp -a "$PROJECT_ROOT/offline-data/$data_name/." "$PROJECT_ROOT/data/$data_name/"
  fi
done
"$PROJECT_ROOT/scripts/prepare-data-dirs.sh" >/dev/null

$COMPOSE config --quiet
$COMPOSE up -d --wait postgres redis minio

REDIS_KEYS_FILE="$PROJECT_ROOT/offline-data/redis/keys.json"
chmod 0444 "$REDIS_KEYS_FILE"
if ! $COMPOSE run --rm --no-deps \
  -v "$REDIS_KEYS_FILE:/restore/keys.json:ro" \
  --entrypoint python agent-api - <<'PY'
import base64
import json
import os

import redis


def decoded(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))


client = redis.Redis(
    host=os.environ.get("REDIS_HOST", "redis"),
    port=int(os.environ.get("REDIS_PORT", "6379")),
    db=int(os.environ.get("REDIS_DB", "0")),
    password=os.environ["REDIS_PASSWORD"],
)
if client.dbsize() != 0:
    raise RuntimeError("Redis restore target is not empty")
with open("/restore/keys.json", encoding="utf-8") as stream:
    entries = json.load(stream)
for entry in entries:
    key = decoded(entry["key"])
    kind = entry["type"]
    value = entry["value"]
    if kind == "string":
        client.set(key, decoded(value))
    elif kind == "list" and value:
        client.rpush(key, *(decoded(item) for item in value))
    elif kind == "set" and value:
        client.sadd(key, *(decoded(item) for item in value))
    elif kind == "hash" and value:
        client.hset(key, mapping={decoded(field): decoded(item) for field, item in value})
    elif kind == "zset" and value:
        client.zadd(key, {decoded(member): score for member, score in value})
    elif kind not in {"list", "set", "hash", "zset"}:
        raise RuntimeError(f"Unsupported Redis value type: {kind}")
    if entry["pttl"] > 0:
        client.pexpire(key, entry["pttl"])
print(f"Restored {len(entries)} Redis keys")
PY
then
  chmod 0600 "$REDIS_KEYS_FILE"
  exit 1
fi
chmod 0600 "$REDIS_KEYS_FILE"

$COMPOSE exec -T postgres pg_restore \
  -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" \
  --no-owner \
  --no-privileges \
  --exit-on-error < "$PROJECT_ROOT/offline-data/postgres.dump"

$COMPOSE run --rm --no-deps minio-init >/dev/null
$COMPOSE run --rm --no-deps \
  -v "$PROJECT_ROOT/offline-data/minio:/import:ro" \
  --entrypoint /bin/sh minio-init -ec '
    mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
    mc mirror --overwrite /import/artifacts local/artifacts >/dev/null
    mc mirror --overwrite /import/knowledge local/knowledge >/dev/null
  '

$COMPOSE up -d --wait agent-api frontend
curl -fsS "http://127.0.0.1:$TARGET_API_PORT/health" >/dev/null
curl -fsS "http://127.0.0.1:$TARGET_FRONTEND_PORT/frontend-health" >/dev/null
curl -fsS "http://127.0.0.1:$TARGET_FRONTEND_PORT/health" >/dev/null

echo "Offline restore completed for Compose project $PROJECT_NAME"
echo "Frontend: http://127.0.0.1:$TARGET_FRONTEND_PORT"
