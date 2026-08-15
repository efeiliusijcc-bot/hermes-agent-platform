# Agent Schema and API Gateway v2

This contract keeps the existing `/api/mcp-servers` boundary and does not expose arbitrary external MCP endpoints. Agent-level model names are forwarded through Hermes to the platform's OpenAI-compatible model gateway without rewriting them to the platform default.

## Main APIs

- `POST /api/skills/upload`: multipart ZIP containing `skill.yaml` and `SKILL.md`.
- `POST /api/mcp-servers/{id}/test`: real MCP initialize connectivity probe.
- `PUT /api/mcp-servers/{id}`: updates an MCP registration and resets connectivity status.
- `PUT /api/agents/{id}/schema`: validates and stores input/output JSON Schema.
- `PUT /api/agents/{id}/configuration`: stores the system prompt, prompt template, model, adapter and model settings.
- `POST /api/agents/{id}/publication/api-key`: creates or rotates a key; plaintext is returned once.
- `PUT /api/agents/{id}/publication`: manages `draft/testing/published/disabled` independently of Agent runtime state.
- `PUT /api/agents/{id}/response-mode`: stores the Agent default as `sync` or `stream`.
- `POST /api/public/agents/{id}/run`: requires `X-API-Key` or Bearer authentication, validates structured input/output, and uses the stored response mode unless `?response_mode=sync|stream` overrides it.
- `POST /api/public/agents/{id}/stream`: always returns the SSE form after pre-stream validation succeeds.

Only SHA-256 API Key hashes and a display prefix are stored in PostgreSQL.

## Agent configuration contract

`input_schema` and `output_schema` accept JSON Schema Draft 2020-12. The legacy shorthand remains supported and is normalized before storage:

```json
{
  "topic": {"type": "string", "required": true}
}
```

Prompt templates use `{{variable}}` and nested `{{object.field}}` placeholders. Variables must be declared in the input Schema, except for the platform variables `input`, `agent_id`, `model`, and `current_time`. Missing or undeclared variables fail closed with HTTP 422. Session memory is serialized as untrusted JSON context; it is not rendered as executable prompt instructions.

The supported adapter identifiers are `hermes`, `qwen`, `deepseek`, `gpt`, and `claude`. They share the `chat(messages)` interface. The offline platform routes the selected model through its OpenAI-compatible model gateway; the adapter and selected model are also written to execution metadata.

## Public request and response contract

The v2 request envelope is:

```json
{
  "input": {"topic": "分析企业知识库"},
  "stream": false,
  "session_id": "external-session-1"
}
```

`stream` and `session_id` are optional. A legacy flat object such as `{"topic":"分析企业知识库"}` remains accepted. Unknown fields in a v2 envelope are rejected instead of being treated as legacy input.

A successful synchronous response is:

```json
{
  "agent_id": "knowledge-agent",
  "execution_id": "uuid",
  "status": "success",
  "result": {"summary": "..."},
  "trace": [
    {"stage": "schema_input", "status": "succeeded"},
    {"stage": "hermes_runtime", "status": "succeeded", "run_id": "run_..."},
    {"stage": "schema_output", "status": "succeeded"}
  ]
}
```

## Sync and SSE modes

`sync` keeps the Phase 2 JSON response contract. `stream` returns `Content-Type: text/event-stream` and forwards Hermes Runtime's native `/v1/runs/{run_id}/events` lifecycle instead of splitting a completed answer into simulated chunks.

```bash
curl -N -X POST \
  'http://HOST/api/public/agents/AGENT_ID/stream' \
  -H 'X-API-Key: hap_...' \
  -H 'Content-Type: application/json' \
  --data '{"input":{"topic":"分析企业知识库"},"stream":true}'
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

Synchronous output parsing accepts plain JSON and a single Markdown JSON code fence. If an Output Schema is configured, non-JSON output or Schema mismatch returns HTTP 502 and records the execution as failed.

## Deployment

The `skills` bind mount is writable only because uploaded Skills must persist. Run `scripts/prepare-data-dirs.sh` before Compose so the container UID can write this directory. Existing bundled Skills remain compatible through `SKILL.md + config.yaml`; uploaded Phase 2 packages are normalized to the same runtime layout.

Run `tests/phase10_phase2_platform.sh` on the deployment host after the stack is healthy. It covers the v2 envelope, legacy request, Prompt Template, model override, adapter persistence, API enablement, input/output Schema failures, API Key hashing, Sync JSON, `/stream`, SSE terminal semantics, and call counts. Docker Compose validation is intentionally not run on developer workstations.

For isolated validation beside an existing deployment, use `docker-compose.verify.yml`, a unique Compose project name, private ports, and a separate data directory. Never point the validation project at an existing deployment's bind mounts.

## 116 isolated validation record

On 2026-08-13 this contract was validated on node 116 with a separate verification Compose project, API `127.0.0.1:38188`, frontend `127.0.0.1:38189`, isolated bind-mounted data, and the test-only OpenAI contract stub. The database reached `0005_agent_gateway_contract`; the full Phase 10 script passed, including real Hermes `/v1/runs` model override evidence (`phase10-model`).

The validation project, images, networks, data and ports were removed afterward. The pre-existing nine `hermes-agent-platform` service container IDs remained unchanged and healthy. This was an isolated acceptance run, not a deployment to the existing platform. The older v2.5 offline bundle remains at migration `0004_agent_response_mode` until a new bundle and checksum are explicitly generated.
