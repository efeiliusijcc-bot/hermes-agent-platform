#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
OUTPUT_DIR=${1:-"$PROJECT_ROOT/dist"}
VERSION=$(tr -d '[:space:]' < "$PROJECT_ROOT/VERSION")
CREATED_AT=$(date -u '+%Y%m%dT%H%M%SZ')
BUNDLE_NAME="hermes-agent-platform-v${VERSION}-${CREATED_AT}"

test -f "$PROJECT_ROOT/.env" || {
  echo "Missing runtime configuration: $PROJECT_ROOT/.env" >&2
  exit 1
}
set -a
. "$PROJECT_ROOT/.env"
set +a
PROJECT_NAME=${OFFLINE_SOURCE_PROJECT_NAME:-${HERMES_COMPOSE_PROJECT_NAME:-${COMPOSE_PROJECT_NAME:-agent}}}
HERMES_INTERNAL_NETWORK_NAME=${HERMES_INTERNAL_NETWORK_NAME:-$PROJECT_NAME-internal}
HERMES_EDGE_NETWORK_NAME=${HERMES_EDGE_NETWORK_NAME:-$PROJECT_NAME-edge}
HERMES_PI_RUNTIME_NETWORK_NAME=${HERMES_PI_RUNTIME_NETWORK_NAME:-$PROJECT_NAME-pi-runtime}
HERMES_DEEPSEEK_RUNTIME_NETWORK_NAME=${HERMES_DEEPSEEK_RUNTIME_NETWORK_NAME:-$PROJECT_NAME-deepseek-runtime}
HERMES_DEEPSEEK_HARNESS_NETWORK_NAME=${HERMES_DEEPSEEK_HARNESS_NETWORK_NAME:-$PROJECT_NAME-deepseek-harness}
HERMES_POSTGRES_MCP_TEST_NETWORK_NAME=${HERMES_POSTGRES_MCP_TEST_NETWORK_NAME:-$PROJECT_NAME-postgres-mcp-test-target}
export HERMES_INTERNAL_NETWORK_NAME HERMES_EDGE_NETWORK_NAME HERMES_PI_RUNTIME_NETWORK_NAME
export HERMES_DEEPSEEK_RUNTIME_NETWORK_NAME HERMES_DEEPSEEK_HARNESS_NETWORK_NAME
export HERMES_POSTGRES_MCP_TEST_NETWORK_NAME
. "$PROJECT_ROOT/scripts/compose-compat.sh"
compose_compat_init "$PROJECT_NAME" "$PROJECT_ROOT/docker-compose.yml"

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
mkdir -p "$STAGE_ROOT/offline-data/database-files"

rsync -a \
  --exclude='.git/' \
  --exclude='.codebase-memory/' \
  --exclude='._*' \
  --exclude='.DS_Store' \
  --exclude='__MACOSX/' \
  --exclude='backups/' \
  --exclude='.pytest_cache/' \
  --exclude='**/__pycache__/' \
  --exclude='**/.pytest_cache/' \
  --exclude='.venv/' \
  --exclude='node_modules/' \
  --exclude='frontend/dist/' \
  --exclude='.env' \
  --exclude='data/' \
  --exclude='dist/' \
  --exclude='artifacts/' \
  "$PROJECT_ROOT/" "$STAGE_ROOT/"
test -x "$STAGE_ROOT/scripts/configure-offline-env.sh"

if [ -d "$PROJECT_ROOT/data/hermes" ]; then
  rsync -a \
    --exclude='._*' \
    --exclude='.DS_Store' \
    --exclude='auth.json' \
    --exclude='backups/' \
    --exclude='config.yaml*' \
    --exclude='sessions/' \
    --exclude='logs/' \
    --exclude='home/' \
    --exclude='cache/' \
    --exclude='state.db*' \
    --exclude='gateway*' \
    --exclude='state/gateway*' \
    --exclude='*.pid' \
    --exclude='*.lock' \
    "$PROJECT_ROOT/data/hermes/" "$STAGE_ROOT/offline-data/hermes/"
fi

for data_name in hermes-workspace deepseek-sessions mcp-files database-files; do
  if [ -d "$PROJECT_ROOT/data/$data_name" ]; then
    rsync -a --exclude='._*' --exclude='.DS_Store' \
      "$PROJECT_ROOT/data/$data_name/" "$STAGE_ROOT/offline-data/$data_name/"
  fi
done

compose_compat_run exec -T postgres pg_dump \
  -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" \
  --format=custom \
  --no-owner \
  --no-privileges > "$STAGE_ROOT/offline-data/postgres.dump"

redis_id=$(compose_compat_run ps -q redis | sed -n '1p')
test -n "$redis_id"
compose_compat_run exec -T redis sh -ec \
  'rm -f /tmp/hermes-offline-export.rdb; REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli --rdb /tmp/hermes-offline-export.rdb >/dev/null'
docker_compat_run cp "$redis_id:/tmp/hermes-offline-export.rdb" "$STAGE_ROOT/offline-data/redis/dump.rdb" >/dev/null
compose_compat_run exec -T redis rm -f /tmp/hermes-offline-export.rdb
compose_compat_run exec -T agent-api python - <<'PY' > "$STAGE_ROOT/offline-data/redis/keys.json"
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
    elif kind == "stream":
        entry["value"] = [
            {
                "id": encoded(message_id),
                "fields": [
                    [encoded(field), encoded(value)]
                    for field, value in sorted(fields.items())
                ],
            }
            for message_id, fields in client.xrange(key)
        ]
        entry["groups"] = [
            {
                "name": encoded(group[b"name"]),
                "last_delivered_id": encoded(group[b"last-delivered-id"]),
            }
            for group in client.xinfo_groups(key)
        ]
    else:
        raise RuntimeError(f"Unsupported Redis value type: {kind}")
    entries.append(entry)
json.dump(entries, fp=os.sys.stdout, ensure_ascii=True, separators=(",", ":"))
PY
chmod 0600 "$STAGE_ROOT/offline-data/redis/keys.json"

compose_compat_run run --rm --no-deps \
  -v "$STAGE_ROOT/offline-data/minio:/export" \
  --entrypoint /bin/sh minio-init -ec '
    mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
    mc mirror --overwrite local/artifacts /export/artifacts >/dev/null
    mc mirror --overwrite local/knowledge /export/knowledge >/dev/null
  '

image_refs=$(compose_compat_run --profile '*' config --images | sort -u)
test -n "$image_refs"
printf '%s\n' "$image_refs" > "$STAGE_ROOT/OFFLINE_IMAGES.txt"
set -- $image_refs
for image_ref in "$@"; do
  docker_compat_run image inspect "$image_ref" >/dev/null
done
docker_compat_run save -o "$STAGE_ROOT/images.tar" "$@"

database_migration_head=$(compose_compat_run exec -T postgres psql \
  -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc 'select version_num from alembic_version;' | tr -d '[:space:]')
test -n "$database_migration_head"

PROJECT_ROOT="$PROJECT_ROOT" STAGE_ROOT="$STAGE_ROOT" python3 - <<'PY'
from pathlib import Path
import os

source_root = Path(os.environ["PROJECT_ROOT"])
stage_root = Path(os.environ["STAGE_ROOT"])
secret_values: dict[str, bytes] = {}
for line in (source_root / ".env").read_text(encoding="utf-8", errors="ignore").splitlines():
    if not line or line.lstrip().startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    if any(marker in key.upper() for marker in ("PASSWORD", "API_KEY", "SIGNING_KEY", "ENCRYPTION_KEY", "TOKEN", "SECRET")):
        if len(value) >= 8 and "change_me" not in value and "replace_with" not in value:
            secret_values[key] = value.encode("utf-8")

findings: list[tuple[str, str]] = []
for path in stage_root.rglob("*"):
    if not path.is_file() or path.name == "images.tar" or path.stat().st_size > 100 * 1024 * 1024:
        continue
    content = path.read_bytes()
    for key, value in secret_values.items():
        if value in content:
            findings.append((key, str(path.relative_to(stage_root))))
if findings:
    for key, path in sorted(set(findings)):
        print(f"Sensitive source value detected: {key} in {path}", file=os.sys.stderr)
    raise SystemExit(1)
print("Sensitive source value scan passed")
PY

cat > "$STAGE_ROOT/OFFLINE_MANIFEST.txt" <<EOF
product=Hermes Agent Platform
version=$VERSION
created_at_utc=$CREATED_AT
source_compose_project=$PROJECT_NAME
runtime_release=${HERMES_RUNTIME_VERSION:-unknown}
pi_core_release=${PI_RUNTIME_VERSION:-unknown}
deepseek_harness_release=${DEEPSEEK_RUNTIME_VERSION:-unknown}
database_migration_head=$database_migration_head
capability_platform_default=true
capability_gateway_default=true
console_bff_default=true
source_recall_default=false
deepseek_transport=json-rpc-2.0-via-private-unix-socket-dispatcher
source_env_included=false
runtime_sensitive_files_included=false
runtime_transient_excludes=config,auth,request-dumps,logs,caches,state-db,pid-locks
target_env_generation=offline-network-none
data_format=postgres-custom-dump,redis-rdb-and-logical,minio-object-mirror,bind-directory-copy
redis_stream_restore=entries-and-groups-without-pending-consumer-ownership
EOF

(
  cd "$STAGE_ROOT"
  find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
  sha256sum -c SHA256SUMS >/dev/null
)

ARCHIVE="$OUTPUT_DIR/$BUNDLE_NAME.tar.gz"
if command -v pigz >/dev/null 2>&1; then
  tar -C "$STAGE_PARENT" -cf - "$BUNDLE_NAME" | pigz -1 > "$ARCHIVE"
else
  tar -C "$STAGE_PARENT" -cf - "$BUNDLE_NAME" | gzip -1 > "$ARCHIVE"
fi
chmod 0600 "$ARCHIVE"
(
  cd "$OUTPUT_DIR"
  sha256sum "$(basename "$ARCHIVE")" > "$(basename "$ARCHIVE").sha256"
)
chmod 0600 "$ARCHIVE.sha256"

echo "Offline bundle created: $ARCHIVE"
echo "Archive checksum: $ARCHIVE.sha256"
