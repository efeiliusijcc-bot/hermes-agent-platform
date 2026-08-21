#!/usr/bin/env sh

# Docker / Compose compatibility helpers. Supports both the Docker Compose
# plugin (`docker compose`) and the standalone command (`docker-compose`).
# Call compose_compat_init PROJECT_NAME COMPOSE_FILE before other helpers.

docker_compat_init() {
  DOCKER_COMPAT_BIN=${OFFLINE_DOCKER_EXECUTABLE:-docker}
  if command -v "$DOCKER_COMPAT_BIN" >/dev/null 2>&1; then
    :
  elif [ -x "$DOCKER_COMPAT_BIN" ]; then
    :
  else
    echo "Docker executable not found: $DOCKER_COMPAT_BIN" >&2
    return 1
  fi
  export DOCKER_COMPAT_BIN
}

docker_compat_run() {
  "$DOCKER_COMPAT_BIN" "$@"
}

compose_compat_init() {
  test "$#" = 2 || {
    echo "compose_compat_init requires PROJECT_NAME and COMPOSE_FILE" >&2
    return 1
  }
  COMPOSE_COMPAT_PROJECT=$1
  COMPOSE_COMPAT_FILE=$2
  test -f "$COMPOSE_COMPAT_FILE" || {
    echo "Compose file does not exist: $COMPOSE_COMPAT_FILE" >&2
    return 1
  }
  docker_compat_init

  compose_compat_requested_mode=${OFFLINE_COMPOSE_MODE:-auto}
  case "$compose_compat_requested_mode" in
    auto)
      if docker_compat_run compose version >/dev/null 2>&1; then
        COMPOSE_COMPAT_MODE=plugin
        COMPOSE_COMPAT_BIN=$DOCKER_COMPAT_BIN
      elif command -v "${OFFLINE_COMPOSE_EXECUTABLE:-docker-compose}" >/dev/null 2>&1; then
        COMPOSE_COMPAT_MODE=standalone
        COMPOSE_COMPAT_BIN=${OFFLINE_COMPOSE_EXECUTABLE:-docker-compose}
      elif [ -n "${OFFLINE_COMPOSE_EXECUTABLE:-}" ] && [ -x "$OFFLINE_COMPOSE_EXECUTABLE" ]; then
        COMPOSE_COMPAT_MODE=standalone
        COMPOSE_COMPAT_BIN=$OFFLINE_COMPOSE_EXECUTABLE
      else
        echo "Docker Compose was not found; install the plugin or docker-compose command" >&2
        return 1
      fi
      ;;
    plugin)
      docker_compat_run compose version >/dev/null 2>&1 || {
        echo "Requested Compose plugin is unavailable" >&2
        return 1
      }
      COMPOSE_COMPAT_MODE=plugin
      COMPOSE_COMPAT_BIN=$DOCKER_COMPAT_BIN
      ;;
    standalone)
      COMPOSE_COMPAT_BIN=${OFFLINE_COMPOSE_EXECUTABLE:-docker-compose}
      if command -v "$COMPOSE_COMPAT_BIN" >/dev/null 2>&1; then
        :
      elif [ -x "$COMPOSE_COMPAT_BIN" ]; then
        :
      else
        echo "Standalone Compose executable not found: $COMPOSE_COMPAT_BIN" >&2
        return 1
      fi
      COMPOSE_COMPAT_MODE=standalone
      ;;
    *)
      echo "Invalid OFFLINE_COMPOSE_MODE: $compose_compat_requested_mode (expected auto, plugin, or standalone)" >&2
      return 1
      ;;
  esac
  export COMPOSE_COMPAT_PROJECT COMPOSE_COMPAT_FILE COMPOSE_COMPAT_MODE COMPOSE_COMPAT_BIN
  echo "Compose command mode: $COMPOSE_COMPAT_MODE"
}

compose_compat_run() {
  case "$COMPOSE_COMPAT_MODE" in
    plugin)
      docker_compat_run compose -p "$COMPOSE_COMPAT_PROJECT" -f "$COMPOSE_COMPAT_FILE" "$@"
      ;;
    standalone)
      "$COMPOSE_COMPAT_BIN" -p "$COMPOSE_COMPAT_PROJECT" -f "$COMPOSE_COMPAT_FILE" "$@"
      ;;
    *)
      echo "compose_compat_init was not called" >&2
      return 1
      ;;
  esac
}

compose_compat_run_for() {
  test "$#" -ge 3 || {
    echo "compose_compat_run_for requires PROJECT_NAME, COMPOSE_FILE, and arguments" >&2
    return 1
  }
  compose_compat_for_project=$1
  compose_compat_for_file=$2
  shift 2
  case "$COMPOSE_COMPAT_MODE" in
    plugin)
      docker_compat_run compose -p "$compose_compat_for_project" -f "$compose_compat_for_file" "$@"
      ;;
    standalone)
      "$COMPOSE_COMPAT_BIN" -p "$compose_compat_for_project" -f "$compose_compat_for_file" "$@"
      ;;
    *)
      echo "compose_compat_init was not called" >&2
      return 1
      ;;
  esac
}

compose_compat_config_check() {
  if compose_compat_run config --help 2>&1 | grep -q -- '--quiet'; then
    compose_compat_run config --quiet
  else
    compose_compat_run config >/dev/null
  fi
}

compose_compat_select_wait_mode() {
  COMPOSE_COMPAT_WAIT_MODE=${OFFLINE_COMPOSE_WAIT_MODE:-manual}
  case "$COMPOSE_COMPAT_WAIT_MODE" in
    auto)
      if compose_compat_run up --help 2>&1 | grep -q -- '--wait'; then
        COMPOSE_COMPAT_WAIT_MODE=native
      else
        COMPOSE_COMPAT_WAIT_MODE=manual
      fi
      ;;
    native)
      if ! compose_compat_run up --help 2>&1 | grep -q -- '--wait'; then
        echo "Docker Compose does not support 'up --wait'; use manual or auto mode" >&2
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
    ''|*[!0-9]*|0)
      echo "OFFLINE_SERVICE_WAIT_TIMEOUT_SECONDS must be a positive integer" >&2
      return 1
      ;;
  esac
  export COMPOSE_COMPAT_WAIT_MODE COMPOSE_COMPAT_WAIT_TIMEOUT_SECONDS
  echo "Compose readiness mode: $COMPOSE_COMPAT_WAIT_MODE"
}

compose_compat_recent_logs() {
  compose_compat_log_service=$1
  echo "Recent logs for $compose_compat_log_service:" >&2
  compose_compat_run logs --tail=80 "$compose_compat_log_service" >&2 || true
}

compose_compat_wait_service() {
  compose_compat_service=$1
  compose_compat_deadline=$(( $(date +%s) + COMPOSE_COMPAT_WAIT_TIMEOUT_SECONDS ))
  compose_compat_last_state=missing
  compose_compat_last_health=none

  while :; do
    compose_compat_container_id=$(compose_compat_run ps -q "$compose_compat_service" 2>/dev/null | sed -n '1p')
    if [ -n "$compose_compat_container_id" ]; then
      if ! compose_compat_last_state=$(docker_compat_run inspect --format '{{.State.Status}}' "$compose_compat_container_id" 2>/dev/null); then
        compose_compat_last_state=unknown
      fi
      if ! compose_compat_last_health=$(docker_compat_run inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$compose_compat_container_id" 2>/dev/null); then
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
    compose_compat_run up -d --wait "$@"
    return
  fi

  compose_compat_run up -d "$@"
  for compose_compat_service_name in "$@"; do
    compose_compat_wait_service "$compose_compat_service_name"
  done
}
