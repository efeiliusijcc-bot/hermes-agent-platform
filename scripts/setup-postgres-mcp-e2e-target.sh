#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PROJECT_NAME=${HERMES_COMPOSE_PROJECT_NAME:-agent}
TEST_NETWORK=${HERMES_POSTGRES_MCP_TEST_NETWORK_NAME:-agent-postgres-test}
COMPOSE_PROFILES=postgres-mcp-e2e
export COMPOSE_PROFILES
. "$PROJECT_ROOT/scripts/compose-compat.sh"
compose_compat_init "$PROJECT_NAME" "$PROJECT_ROOT/docker-compose.yml"
compose_compat_select_wait_mode

compose_compat_up_and_wait postgres-mcp-test-db

postgres_mcp_id=$(compose_compat_run ps -q postgres-mcp | sed -n '1p')
test_postgres_id=$(compose_compat_run ps -q postgres-mcp-test-db | sed -n '1p')
test -n "$postgres_mcp_id" || {
  echo "postgres-mcp is not running" >&2
  exit 1
}
test -n "$test_postgres_id" || {
  echo "postgres-mcp-test-db is not running" >&2
  exit 1
}

if ! docker_compat_run inspect --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' \
  "$postgres_mcp_id" | grep -Fxq "$TEST_NETWORK"; then
  docker_compat_run network connect "$TEST_NETWORK" "$postgres_mcp_id"
fi

docker_compat_run inspect --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' \
  "$postgres_mcp_id" | grep -Fx "$TEST_NETWORK"
docker_compat_run inspect --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' \
  "$test_postgres_id" | grep -Fx "$TEST_NETWORK"

echo "PostgreSQL MCP E2E target is ready"
echo "host=postgres-mcp-test-db port=5432 maintenance_database=postgres"
echo "username=hermes_reader password=postgres-mcp-e2e-reader"
echo "databases=business_db,analytics_db (private_db is intentionally denied)"
