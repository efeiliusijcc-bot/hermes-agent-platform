#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
ENV_FILE=${1:-"$PROJECT_ROOT/.env"}

if [ ! -f "$ENV_FILE" ]; then
  echo "Environment file does not exist: $ENV_FILE" >&2
  exit 1
fi

if grep -q '^MCP_GATEWAY_SIGNING_KEY=.' "$ENV_FILE"; then
  echo "MCP gateway signing key is already configured"
  exit 0
fi

umask 077
signing_key=$(openssl rand -hex 32)
printf '\nMCP_GATEWAY_SIGNING_KEY=%s\n' "$signing_key" >>"$ENV_FILE"
echo "MCP gateway signing key was generated without printing its value"
