#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
ENV_FILE=${1:-"$PROJECT_ROOT/.env"}

if [ ! -f "$ENV_FILE" ]; then
  echo "Environment file does not exist: $ENV_FILE" >&2
  exit 1
fi

umask 077
chmod 0600 "$ENV_FILE"

generated=0
if ! grep -q '^MCP_GATEWAY_SIGNING_KEY=.' "$ENV_FILE"; then
  signing_key=$(openssl rand -hex 32)
  printf '\nMCP_GATEWAY_SIGNING_KEY=%s\n' "$signing_key" >>"$ENV_FILE"
  echo "MCP gateway signing key was generated without printing its value"
  generated=1
fi

if ! grep -q '^PI_RUNTIME_API_KEY=.' "$ENV_FILE"; then
  runtime_key=$(openssl rand -base64 48 | tr -d '\n')
  printf '\nPI_RUNTIME_API_KEY=%s\n' "$runtime_key" >>"$ENV_FILE"
  echo "Pi Runtime API key was generated without printing its value"
  generated=1
fi

if ! grep -q '^DEEPSEEK_RUNTIME_API_KEY=.' "$ENV_FILE"; then
  deepseek_runtime_key=$(openssl rand -base64 48 | tr -d '\n')
  printf '\nDEEPSEEK_RUNTIME_API_KEY=%s\n' "$deepseek_runtime_key" >>"$ENV_FILE"
  echo "DeepSeek Runtime API key was generated without printing its value"
  generated=1
fi

if ! grep -q '^MODEL_REGISTRY_ENCRYPTION_KEY=.' "$ENV_FILE"; then
  encryption_key=$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n')
  printf '\nMODEL_REGISTRY_ENCRYPTION_KEY=%s\n' "$encryption_key" >>"$ENV_FILE"
  echo "Model registry encryption key was generated without printing its value"
  generated=1
fi

if [ "$generated" -eq 0 ]; then
  echo "Runtime secrets are already configured"
fi
