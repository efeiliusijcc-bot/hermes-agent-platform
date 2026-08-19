#!/usr/bin/env sh

# Compatibility helpers for Docker Compose releases that predate `up --wait`
# or `config --quiet`. The caller must set COMPOSE to the complete Compose
# command before invoking these functions.

compose_compat_config_check() {
  if $COMPOSE config --help 2>&1 | grep -q -- '--quiet'; then
    $COMPOSE config --quiet
  else
    $COMPOSE config >/dev/null
  fi
}

compose_compat_select_wait_mode() {
  COMPOSE_COMPAT_WAIT_MODE=${OFFLINE_COMPOSE_WAIT_MODE:-auto}
  case "$COMPOSE_COMPAT_WAIT_MODE" in
    auto)
      if $COMPOSE up --help 2>&1 | grep -q -- '--wait'; then
        COMPOSE_COMPAT_WAIT_MODE=native
      else
        COMPOSE_COMPAT_WAIT_MODE=manual
      fi
      ;;
    native)
      if ! $COMPOSE up --help 2>&1 | grep -q -- '--wait'; then
        echo "Docker Compose does not support 'up --wait'; use OFFLINE_COMPOSE_WAIT_MODE=manual or auto" >&2
        return 1
      fi
      ;;
    manual) ;;
    *)
      echo "Invalid OFFLINE_COMPOSE_WAIT_MODE: $COMPOSE_COMPAT_WAIT_MODE (expected auto, native, or manual)" >&2
      return 1
      ;;
  esac

  COMPOSE_COMPAT_WAIT_TIMEOUT_SECONDS=${OFFLINE_SERVICE_WAIT_TIMEOUT_SECONDS:-300}
  case "$COMPOSE_COMPAT_WAIT_TIMEOUT_SECONDS" in
    ''|*[!0-9]*)
      echo "OFFLINE_SERVICE_WAIT_TIMEOUT_SECONDS must be a positive integer" >&2
      return 1
      ;;
    0)
      echo "OFFLINE_SERVICE_WAIT_TIMEOUT_SECONDS must be greater than zero" >&2
      return 1
      ;;
  esac
  export COMPOSE_COMPAT_WAIT_MODE COMPOSE_COMPAT_WAIT_TIMEOUT_SECONDS
  echo "Compose readiness mode: $COMPOSE_COMPAT_WAIT_MODE"
}

compose_compat_recent_logs() {
  compose_compat_log_service=$1
  echo "Recent logs for $compose_compat_log_service:" >&2
  $COMPOSE logs --tail=80 "$compose_compat_log_service" >&2 || true
}

compose_compat_wait_service() {
  compose_compat_service=$1
  compose_compat_deadline=$(( $(date +%s) + COMPOSE_COMPAT_WAIT_TIMEOUT_SECONDS ))
  compose_compat_last_state=missing
  compose_compat_last_health=none

  while :; do
    compose_compat_container_id=$($COMPOSE ps -q "$compose_compat_service" 2>/dev/null | sed -n '1p')
    if [ -n "$compose_compat_container_id" ]; then
      if ! compose_compat_last_state=$(docker inspect --format '{{.State.Status}}' "$compose_compat_container_id" 2>/dev/null); then
        compose_compat_last_state=unknown
      fi
      if ! compose_compat_last_health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$compose_compat_container_id" 2>/dev/null); then
        compose_compat_last_health=unknown
      fi

      case "$compose_compat_last_state:$compose_compat_last_health" in
        running:healthy|running:none)
          echo "Service ready: $compose_compat_service ($compose_compat_last_state/$compose_compat_last_health)"
          return 0
          ;;
        *:unhealthy)
          echo "Service became unhealthy: $compose_compat_service" >&2
          compose_compat_recent_logs "$compose_compat_service"
          return 1
          ;;
        exited:*|dead:*|paused:*)
          echo "Service stopped before becoming ready: $compose_compat_service ($compose_compat_last_state/$compose_compat_last_health)" >&2
          compose_compat_recent_logs "$compose_compat_service"
          return 1
          ;;
      esac
    fi

    if [ "$(date +%s)" -ge "$compose_compat_deadline" ]; then
      echo "Timed out waiting for service: $compose_compat_service ($compose_compat_last_state/$compose_compat_last_health)" >&2
      compose_compat_recent_logs "$compose_compat_service"
      return 1
    fi
    sleep 2
  done
}

compose_compat_up_and_wait() {
  test "$#" -gt 0 || {
    echo "compose_compat_up_and_wait requires at least one service" >&2
    return 1
  }

  if [ "$COMPOSE_COMPAT_WAIT_MODE" = native ]; then
    $COMPOSE up -d --wait "$@"
    return
  fi

  $COMPOSE up -d "$@"
  for compose_compat_service_name in "$@"; do
    compose_compat_wait_service "$compose_compat_service_name"
  done
}
