#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
PROJECT_NAME=${HERMES_COMPOSE_PROJECT_NAME:-hermes-agent-platform}
COMPOSE="docker compose -p $PROJECT_NAME -f $PROJECT_ROOT/docker-compose.yml"
. "$PROJECT_ROOT/scripts/compose-compat.sh"
compose_compat_select_wait_mode

test -f "$PROJECT_ROOT/.env" || {
  echo "missing deployment file: $PROJECT_ROOT/.env" >&2
  exit 1
}

compose_compat_config_check
compose_compat_up_and_wait postgres redis minio

postgres_id=$($COMPOSE ps -q postgres)
redis_id=$($COMPOSE ps -q redis)
minio_id=$($COMPOSE ps -q minio)

for container_id in "$postgres_id" "$redis_id" "$minio_id"; do
  test -n "$container_id"
  test "$(docker inspect --format '{{.State.Health.Status}}' "$container_id")" = "healthy"
  test "$(docker inspect --format '{{json .HostConfig.PortBindings}}' "$container_id")" = "{}"
done

$COMPOSE exec -T postgres psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" <<'SQL'
CREATE TABLE IF NOT EXISTS infrastructure_probe (
  id integer PRIMARY KEY,
  value text NOT NULL
);
INSERT INTO infrastructure_probe(id, value)
VALUES (1, 'phase1-ok')
ON CONFLICT (id) DO UPDATE SET value = EXCLUDED.value;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
    RAISE EXCEPTION 'vector extension is not installed';
  END IF;
END
$$;
SQL

$COMPOSE exec -T redis sh -ec 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli SET hap:phase1:probe phase1-ok | grep -q OK'
$COMPOSE run --rm minio-init

$COMPOSE exec -T postgres bash -ec 'exec 3<>/dev/tcp/redis/6379; exec 4<>/dev/tcp/minio/9000'

$COMPOSE restart postgres redis minio
compose_compat_up_and_wait postgres redis minio

test "$($COMPOSE exec -T postgres psql -At -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "SELECT value FROM infrastructure_probe WHERE id = 1")" = "phase1-ok"
test "$($COMPOSE exec -T redis sh -ec 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli GET hap:phase1:probe')" = "phase1-ok"
$COMPOSE run --rm --entrypoint /bin/sh minio-init -ec '
  mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
  test "$(mc cat local/artifacts/phase1/probe.txt)" = "phase1-ok"
'

test "$($COMPOSE ps -q postgres redis minio | wc -l | tr -d ' ')" = "3"
echo "Phase 1 infrastructure validation passed"
