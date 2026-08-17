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
  "$PROJECT_ROOT/data/hermes-workspace" \
  "$PROJECT_ROOT/data/deepseek-sessions" \
  "$PROJECT_ROOT/data/artifacts" \
  "$PROJECT_ROOT/data/mcp-files" \
  "$PROJECT_ROOT/skills"

chmod 0750 "$PROJECT_ROOT/data"
chmod 0750 \
  "$PROJECT_ROOT/data/postgres" \
  "$PROJECT_ROOT/data/redis" \
  "$PROJECT_ROOT/data/minio" \
  "$PROJECT_ROOT/data/hermes" \
  "$PROJECT_ROOT/data/mcp-files"

chmod 0770 "$PROJECT_ROOT/skills"
if [ "$(id -u)" = "0" ]; then
  chown -R "${AGENT_API_UID:-10002}:${AGENT_API_GID:-10002}" "$PROJECT_ROOT/skills"
fi

chmod 2770 "$PROJECT_ROOT/data/hermes-workspace" "$PROJECT_ROOT/data/artifacts"
if [ "$(id -u)" = "0" ]; then
  chown -R "${AGENT_API_UID:-10002}:${WORKSPACE_SHARED_GID:-10003}" \
    "$PROJECT_ROOT/data/hermes-workspace" "$PROJECT_ROOT/data/artifacts"
  chown -R "${DEEPSEEK_RUNTIME_UID:-10004}:${DEEPSEEK_RUNTIME_GID:-10004}" \
    "$PROJECT_ROOT/data/deepseek-sessions"
  chown -R "${MCP_GATEWAY_UID:-10001}:${MCP_GATEWAY_GID:-10001}" \
    "$PROJECT_ROOT/data/mcp-files"
fi
chmod 2770 "$PROJECT_ROOT/data/deepseek-sessions"

echo "Persistent data directories prepared under $PROJECT_ROOT/data"
