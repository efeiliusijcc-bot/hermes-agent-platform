#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

umask 027
mkdir -p \
  "$PROJECT_ROOT/data/postgres" \
  "$PROJECT_ROOT/data/redis" \
  "$PROJECT_ROOT/data/minio" \
  "$PROJECT_ROOT/data/hermes" \
  "$PROJECT_ROOT/data/hermes-workspace"

chmod 0750 "$PROJECT_ROOT/data"
chmod 0750 \
  "$PROJECT_ROOT/data/postgres" \
  "$PROJECT_ROOT/data/redis" \
  "$PROJECT_ROOT/data/minio" \
  "$PROJECT_ROOT/data/hermes"

chmod 0770 "$PROJECT_ROOT/data/hermes-workspace"
if [ "$(id -u)" = "0" ]; then
  chown -R "${HERMES_RUNTIME_UID:-10000}:${HERMES_RUNTIME_GID:-10000}" \
    "$PROJECT_ROOT/data/hermes-workspace"
fi

echo "Persistent data directories prepared under $PROJECT_ROOT/data"
