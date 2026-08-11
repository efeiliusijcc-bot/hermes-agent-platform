#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

required_dirs="backend frontend services skills configs docker docs tests scripts"
for directory in $required_dirs; do
  test -d "$PROJECT_ROOT/$directory" || {
    echo "missing directory: $directory" >&2
    exit 1
  }
done

required_files="README.md .env.example .gitignore docker-compose.yml docs/development-guidelines.md docs/hermes_agent_offline_platform_detailed_design.md docker/README.md"
for file in $required_files; do
  test -s "$PROJECT_ROOT/$file" || {
    echo "missing or empty file: $file" >&2
    exit 1
  }
done

if [ "${HAP_VALIDATE_COMPOSE:-0}" = "1" ]; then
  command -v docker >/dev/null 2>&1 || {
    echo "docker is required when HAP_VALIDATE_COMPOSE=1" >&2
    exit 1
  }
  docker compose -p hermes-agent-platform -f "$PROJECT_ROOT/docker-compose.yml" config --quiet
fi

echo "Phase 0 validation passed"
