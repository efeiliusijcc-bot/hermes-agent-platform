# Phase 2 Registry and Agent API

Phase 2 keeps the existing `/api/mcp-servers` contract and the platform MCP Gateway boundary. It does not expose arbitrary external MCP endpoints.

## Main APIs

- `POST /api/skills/upload`: multipart ZIP containing `skill.yaml` and `SKILL.md`.
- `POST /api/mcp-servers/{id}/test`: real MCP initialize connectivity probe.
- `PUT /api/mcp-servers/{id}`: updates an MCP registration and resets connectivity status.
- `PUT /api/agents/{id}/schema`: validates and stores input/output JSON Schema.
- `POST /api/agents/{id}/publication/api-key`: creates or rotates a key; plaintext is returned once.
- `PUT /api/agents/{id}/publication`: manages `draft/testing/published/disabled` independently of Agent runtime state.
- `POST /api/public/agents/{id}/run`: requires `X-API-Key` or Bearer authentication and validates structured input/output.

Only SHA-256 API Key hashes and a display prefix are stored in PostgreSQL.

## Deployment

The `skills` bind mount is writable only because uploaded Skills must persist. Run `scripts/prepare-data-dirs.sh` before Compose so the container UID can write this directory. Existing bundled Skills remain compatible through `SKILL.md + config.yaml`; uploaded Phase 2 packages are normalized to the same runtime layout.

Run `tests/phase10_phase2_platform.sh` on the deployment host after the stack is healthy. Docker Compose validation is intentionally not run on developer workstations.
