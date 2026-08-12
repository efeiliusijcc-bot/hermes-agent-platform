# Phase 2 Registry and Agent API

Phase 2 keeps the existing `/api/mcp-servers` contract and the platform MCP Gateway boundary. It does not expose arbitrary external MCP endpoints.

## Main APIs

- `POST /api/skills/upload`: multipart ZIP containing `skill.yaml` and `SKILL.md`.
- `POST /api/mcp-servers/{id}/test`: real MCP initialize connectivity probe.
- `PUT /api/mcp-servers/{id}`: updates an MCP registration and resets connectivity status.
- `PUT /api/agents/{id}/schema`: validates and stores input/output JSON Schema.
- `POST /api/agents/{id}/publication/api-key`: creates or rotates a key; plaintext is returned once.
- `PUT /api/agents/{id}/publication`: manages `draft/testing/published/disabled` independently of Agent runtime state.
- `PUT /api/agents/{id}/response-mode`: stores the Agent default as `sync` or `stream`.
- `POST /api/public/agents/{id}/run`: requires `X-API-Key` or Bearer authentication, validates structured input/output, and uses the stored response mode unless `?response_mode=sync|stream` overrides it.

Only SHA-256 API Key hashes and a display prefix are stored in PostgreSQL.

## Sync and SSE modes

`sync` keeps the Phase 2 JSON response contract. `stream` returns `Content-Type: text/event-stream` and forwards Hermes Runtime's native `/v1/runs/{run_id}/events` lifecycle instead of splitting a completed answer into simulated chunks.

```bash
curl -N -X POST \
  'http://HOST/api/public/agents/AGENT_ID/run?response_mode=stream' \
  -H 'X-API-Key: hap_...' \
  -H 'Content-Type: application/json' \
  --data '{"topic":"分析企业知识库"}'
```

The stable platform event names are:

- `start`: execution and Agent identifiers are ready.
- `trace`: schema, runtime reasoning, and subagent lifecycle events.
- `tool`: Hermes tool start/completion/failure events.
- `token`: a real `message.delta` from Hermes Runtime.
- `end`: successful terminal event and validated public result.
- `error`: terminal failure after the SSE connection has started.
- `keepalive`: the upstream run is still active without a new business event.

Pre-stream authentication, publication, Agent status, and input-schema failures keep their normal HTTP status (`401`, `404`, `409`, `422`). After `200 text/event-stream` has started, runtime or output-schema failures are represented by an `error` event. A successful public call is counted only after the `end` result is produced.

## Deployment

The `skills` bind mount is writable only because uploaded Skills must persist. Run `scripts/prepare-data-dirs.sh` before Compose so the container UID can write this directory. Existing bundled Skills remain compatible through `SKILL.md + config.yaml`; uploaded Phase 2 packages are normalized to the same runtime layout.

Run `tests/phase10_phase2_platform.sh` on the deployment host after the stack is healthy. Docker Compose validation is intentionally not run on developer workstations.
