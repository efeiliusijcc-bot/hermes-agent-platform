#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PROJECT_NAME=${HERMES_COMPOSE_PROJECT_NAME:-hermes-agent-platform}
TEST_NETWORK=${HERMES_POSTGRES_MCP_TEST_NETWORK_NAME:-hermes-agent-platform-postgres-mcp-test-target}
COMPOSE="docker compose -p $PROJECT_NAME -f $PROJECT_ROOT/docker-compose.yml"

$COMPOSE --profile postgres-mcp-e2e up -d --no-deps --wait --pull never postgres-mcp-test-db

postgres_mcp_id=$($COMPOSE ps -q postgres-mcp)
test_postgres_id=$($COMPOSE --profile postgres-mcp-e2e ps -q postgres-mcp-test-db)
test -n "$postgres_mcp_id" || {
  echo "postgres-mcp is not running" >&2
  exit 1
}
test -n "$test_postgres_id" || {
  echo "postgres-mcp-test-db is not running" >&2
  exit 1
}

if ! docker inspect --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' \
  "$postgres_mcp_id" | grep -Fxq "$TEST_NETWORK"; then
  docker network connect "$TEST_NETWORK" "$postgres_mcp_id"
fi

docker inspect --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' \
  "$postgres_mcp_id" | grep -Fx "$TEST_NETWORK"
docker inspect --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' \
  "$test_postgres_id" | grep -Fx "$TEST_NETWORK"

echo "PostgreSQL MCP E2E target is ready"
echo "host=postgres-mcp-test-db port=5432 maintenance_database=postgres"
echo "username=hermes_reader password=postgres-mcp-e2e-reader"
echo "databases=business_db,analytics_db (private_db is intentionally denied)"
