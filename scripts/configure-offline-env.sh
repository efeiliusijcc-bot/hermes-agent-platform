#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
ENV_FILE="$PROJECT_ROOT/.env"
ENV_EXAMPLE="$PROJECT_ROOT/.env.example"
IMAGES_FILE="$PROJECT_ROOT/images.tar"
GENERATOR_IMAGE=${OFFLINE_SECRET_GENERATOR_IMAGE:-hermes-agent-platform/agent-api:capability-v1}

test -f "$ENV_EXAMPLE" || {
  echo "Offline bundle is missing .env.example" >&2
  exit 1
}
test -f "$IMAGES_FILE" || {
  echo "Offline bundle is missing images.tar" >&2
  exit 1
}
test ! -e "$ENV_FILE" || {
  echo "Refusing to overwrite existing $ENV_FILE" >&2
  exit 1
}

docker load --input "$IMAGES_FILE" >/dev/null
docker image inspect "$GENERATOR_IMAGE" >/dev/null

if [ -z "${OFFLINE_MODEL_ENDPOINT:-}" ]; then
  printf '内网 OpenAI Compatible 模型地址（例如 http://model:8000/v1）：'
  IFS= read -r OFFLINE_MODEL_ENDPOINT
fi
if [ -z "${OFFLINE_MODEL_NAME:-}" ]; then
  printf '模型名称：'
  IFS= read -r OFFLINE_MODEL_NAME
fi
if [ -z "${OFFLINE_MODEL_API_KEY:-}" ]; then
  printf '模型 API Key（输入不回显）：'
  stty -echo
  IFS= read -r OFFLINE_MODEL_API_KEY
  stty echo
  printf '\n'
fi

test -n "$OFFLINE_MODEL_ENDPOINT" || { echo "模型地址不能为空" >&2; exit 1; }
test -n "$OFFLINE_MODEL_NAME" || { echo "模型名称不能为空" >&2; exit 1; }
test -n "$OFFLINE_MODEL_API_KEY" || { echo "模型 API Key 不能为空" >&2; exit 1; }

generated=$(docker run --rm --network none --entrypoint python "$GENERATOR_IMAGE" -c '
from cryptography.fernet import Fernet
from secrets import token_urlsafe
for _ in range(11):
    print(token_urlsafe(36))
print(Fernet.generate_key().decode("ascii"))
')

POSTGRES_PASSWORD=$(printf '%s\n' "$generated" | sed -n '1p')
REDIS_PASSWORD=$(printf '%s\n' "$generated" | sed -n '2p')
MINIO_ROOT_PASSWORD=$(printf '%s\n' "$generated" | sed -n '3p')
MODEL_GATEWAY_API_KEY=$(printf '%s\n' "$generated" | sed -n '4p')
HERMES_API_KEY=$(printf '%s\n' "$generated" | sed -n '5p')
PI_RUNTIME_API_KEY=$(printf '%s\n' "$generated" | sed -n '6p')
DEEPSEEK_RUNTIME_API_KEY=$(printf '%s\n' "$generated" | sed -n '7p')
MCP_GATEWAY_SIGNING_KEY=$(printf '%s\n' "$generated" | sed -n '8p')
PLATFORM_MANAGEMENT_API_KEY=$(printf '%s\n' "$generated" | sed -n '9p')
SOURCE_RECALL_GATEWAY_API_KEY=$(printf '%s\n' "$generated" | sed -n '10p')
POSTGRES_MCP_TEST_ADMIN_PASSWORD=$(printf '%s\n' "$generated" | sed -n '11p')
MODEL_REGISTRY_ENCRYPTION_KEY=${OFFLINE_MODEL_REGISTRY_ENCRYPTION_KEY:-$(printf '%s\n' "$generated" | sed -n '12p')}

cp "$ENV_EXAMPLE" "$ENV_FILE"
chmod 0600 "$ENV_FILE"

set_value() {
  key=$1
  value=$2
  temp_file=$(mktemp "$PROJECT_ROOT/.env.update.XXXXXX")
  awk -v key="$key" -v value="$value" '
    BEGIN { updated = 0 }
    index($0, key "=") == 1 { print key "=" value; updated = 1; next }
    { print }
    END { if (!updated) print key "=" value }
  ' "$ENV_FILE" > "$temp_file"
  chmod 0600 "$temp_file"
  mv "$temp_file" "$ENV_FILE"
}

set_value POSTGRES_PASSWORD "$POSTGRES_PASSWORD"
set_value REDIS_PASSWORD "$REDIS_PASSWORD"
set_value MINIO_ROOT_PASSWORD "$MINIO_ROOT_PASSWORD"
set_value MODEL_ENDPOINT "$OFFLINE_MODEL_ENDPOINT"
set_value MODEL_API_KEY "$OFFLINE_MODEL_API_KEY"
set_value MODEL_NAME "$OFFLINE_MODEL_NAME"
set_value MODEL_GATEWAY_API_KEY "$MODEL_GATEWAY_API_KEY"
set_value MODEL_REGISTRY_ENCRYPTION_KEY "$MODEL_REGISTRY_ENCRYPTION_KEY"
set_value HERMES_API_KEY "$HERMES_API_KEY"
set_value PI_RUNTIME_API_KEY "$PI_RUNTIME_API_KEY"
set_value DEEPSEEK_RUNTIME_API_KEY "$DEEPSEEK_RUNTIME_API_KEY"
set_value MCP_GATEWAY_SIGNING_KEY "$MCP_GATEWAY_SIGNING_KEY"
set_value PLATFORM_MANAGEMENT_API_KEY "$PLATFORM_MANAGEMENT_API_KEY"
set_value SOURCE_RECALL_ENABLED "false"
set_value SOURCE_RECALL_GATEWAY_API_KEY "$SOURCE_RECALL_GATEWAY_API_KEY"
set_value SOURCE_RECALL_UPSTREAM_ENDPOINT ""
set_value SOURCE_RECALL_UPSTREAM_API_KEY ""
set_value CAPABILITY_PLATFORM_ENABLED "true"
set_value CAPABILITY_GATEWAY_ENABLED "true"
set_value CONSOLE_BFF_ENABLED "true"
set_value POSTGRES_MCP_TEST_ADMIN_PASSWORD "$POSTGRES_MCP_TEST_ADMIN_PASSWORD"
set_value FRONTEND_BIND_HOST "${OFFLINE_FRONTEND_BIND_HOST:-0.0.0.0}"
set_value AGENT_API_BIND_HOST "${OFFLINE_AGENT_API_BIND_HOST:-127.0.0.1}"

unset generated POSTGRES_PASSWORD REDIS_PASSWORD MINIO_ROOT_PASSWORD
unset MODEL_GATEWAY_API_KEY HERMES_API_KEY PI_RUNTIME_API_KEY
unset DEEPSEEK_RUNTIME_API_KEY MCP_GATEWAY_SIGNING_KEY PLATFORM_MANAGEMENT_API_KEY
unset SOURCE_RECALL_GATEWAY_API_KEY POSTGRES_MCP_TEST_ADMIN_PASSWORD
unset MODEL_REGISTRY_ENCRYPTION_KEY OFFLINE_MODEL_API_KEY
unset OFFLINE_MODEL_REGISTRY_ENCRYPTION_KEY

echo "Offline .env created: $ENV_FILE"
echo "Internal secrets were generated locally with --network none and were not printed."
echo "The platform management key is stored only in the target node .env."
