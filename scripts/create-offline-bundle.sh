#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
OUTPUT_DIR=${1:-"$PROJECT_ROOT/dist"}
PROJECT_NAME=${HERMES_COMPOSE_PROJECT_NAME:-hermes-agent-platform}
COMPOSE="docker compose -p $PROJECT_NAME -f $PROJECT_ROOT/docker-compose.yml"
VERSION=$(tr -d '[:space:]' < "$PROJECT_ROOT/VERSION")
CREATED_AT=$(date -u '+%Y%m%dT%H%M%SZ')
BUNDLE_NAME="hermes-agent-platform-v${VERSION}-${CREATED_AT}"

test -f "$PROJECT_ROOT/.env" || {
  echo "Missing runtime configuration: $PROJECT_ROOT/.env" >&2
  exit 1
}

umask 077
mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR=$(CDPATH= cd -- "$OUTPUT_DIR" && pwd)
STAGE_PARENT=$(mktemp -d "$OUTPUT_DIR/.offline-stage.XXXXXX")
STAGE_ROOT="$STAGE_PARENT/$BUNDLE_NAME"

cleanup_stage() {
  rm -rf -- "$STAGE_PARENT"
}
trap cleanup_stage EXIT
trap 'exit 1' HUP INT TERM

mkdir -p \
  "$STAGE_ROOT/offline-data/minio/artifacts" \
  "$STAGE_ROOT/offline-data/minio/knowledge" \
  "$STAGE_ROOT/offline-data/redis" \
  "$STAGE_ROOT/offline-data/hermes" \
  "$STAGE_ROOT/offline-data/hermes-workspace" \
  "$STAGE_ROOT/offline-data/deepseek-sessions" \
  "$STAGE_ROOT/offline-data/mcp-files"

rsync -a \
  --exclude='.git/' \
  --exclude='.codebase-memory/' \
  --exclude='.venv/' \
  --exclude='node_modules/' \
  --exclude='.env' \
  --exclude='data/' \
  --exclude='dist/' \
  --exclude='artifacts/' \
  "$PROJECT_ROOT/" "$STAGE_ROOT/"
cp "$PROJECT_ROOT/.env" "$STAGE_ROOT/.env"
chmod 0600 "$STAGE_ROOT/.env"

for data_name in hermes hermes-workspace deepseek-sessions mcp-files; do
  if [ -d "$PROJECT_ROOT/data/$data_name" ]; then
    rsync -a "$PROJECT_ROOT/data/$data_name/" "$STAGE_ROOT/offline-data/$data_name/"
  fi
done

$COMPOSE exec -T postgres pg_dump \
  -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" \
  --format=custom \
  --no-owner \
  --no-privileges > "$STAGE_ROOT/offline-data/postgres.dump"

redis_id=$($COMPOSE ps -q redis)
test -n "$redis_id"
$COMPOSE exec -T redis sh -ec \
  'rm -f /tmp/hermes-offline-export.rdb; REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --rdb /tmp/hermes-offline-export.rdb >/dev/null'
docker cp "$redis_id:/tmp/hermes-offline-export.rdb" "$STAGE_ROOT/offline-data/redis/dump.rdb" >/dev/null
$COMPOSE exec -T redis rm -f /tmp/hermes-offline-export.rdb
$COMPOSE exec -T agent-api python - <<'PY' > "$STAGE_ROOT/offline-data/redis/keys.json"
import base64
import json
import os

import redis


def encoded(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


client = redis.Redis(
    host=os.environ.get("REDIS_HOST", "redis"),
    port=int(os.environ.get("REDIS_PORT", "6379")),
    db=int(os.environ.get("REDIS_DB", "0")),
    password=os.environ["REDIS_PASSWORD"],
)
entries = []
for key in sorted(client.scan_iter()):
    kind = client.type(key).decode("ascii")
    entry = {"key": encoded(key), "type": kind, "pttl": client.pttl(key)}
    if kind == "string":
        entry["value"] = encoded(client.get(key))
    elif kind == "list":
        entry["value"] = [encoded(value) for value in client.lrange(key, 0, -1)]
    elif kind == "set":
        entry["value"] = [encoded(value) for value in sorted(client.smembers(key))]
    elif kind == "hash":
        entry["value"] = [
            [encoded(field), encoded(value)]
            for field, value in sorted(client.hgetall(key).items())
        ]
    elif kind == "zset":
        entry["value"] = [
            [encoded(member), score]
            for member, score in client.zrange(key, 0, -1, withscores=True)
        ]
    else:
        raise RuntimeError(f"Unsupported Redis value type: {kind}")
    entries.append(entry)
json.dump(entries, fp=os.sys.stdout, ensure_ascii=True, separators=(",", ":"))
PY
chmod 0600 "$STAGE_ROOT/offline-data/redis/keys.json"

$COMPOSE run --rm --no-deps \
  -v "$STAGE_ROOT/offline-data/minio:/export" \
  --entrypoint /bin/sh minio-init -ec '
    mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
    mc mirror --overwrite local/artifacts /export/artifacts >/dev/null
    mc mirror --overwrite local/knowledge /export/knowledge >/dev/null
  '

image_refs=$($COMPOSE config --images | sort -u)
test -n "$image_refs"
printf '%s\n' "$image_refs" > "$STAGE_ROOT/OFFLINE_IMAGES.txt"
set -- $image_refs
for image_ref in "$@"; do
  docker image inspect "$image_ref" >/dev/null
done
docker save --output "$STAGE_ROOT/images.tar" "$@"

cat > "$STAGE_ROOT/OFFLINE_MANIFEST.txt" <<EOF
product=Hermes Agent Platform
version=$VERSION
created_at_utc=$CREATED_AT
source_compose_project=$PROJECT_NAME
hermes_release=v0.20.0
hermes_image=nousresearch/hermes-agent:v2026.8.3@sha256:16788311e2fa3035456bdc1bafb8ec2b1777db64ebf020af9bb7eb73c3712c9e
pi_core_release=0.84.2
pi_runtime_image=hermes-agent-platform/pi-runtime:phase5
deepseek_harness_release=0.1.0-rc.6
deepseek_runtime_image=hermes-agent-platform/deepseek-runtime:phase8
deepseek_transport=json-rpc-2.0-stdio-via-isolated-http-gateway
data_format=postgres-custom-dump,redis-rdb-and-logical,minio-object-mirror,bind-directory-copy
EOF

(
  cd "$STAGE_ROOT"
  find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
  sha256sum -c SHA256SUMS >/dev/null
)

ARCHIVE="$OUTPUT_DIR/$BUNDLE_NAME.tar.gz"
tar -C "$STAGE_PARENT" -cf - "$BUNDLE_NAME" | gzip -1 > "$ARCHIVE"
chmod 0600 "$ARCHIVE"
(
  cd "$OUTPUT_DIR"
  sha256sum "$(basename "$ARCHIVE")" > "$(basename "$ARCHIVE").sha256"
)
chmod 0600 "$ARCHIVE.sha256"

echo "Offline bundle created: $ARCHIVE"
echo "Archive checksum: $ARCHIVE.sha256"
