from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api import agents as agent_api
from app.api.publications import _public_payload
from app.schemas.agent import AgentConfigurationUpdate, AgentCreate
from app.schemas.publication import PublicAgentRunRequest


def test_agent_schema_gateway_fields_are_persisted_by_the_contract() -> None:
    agent = AgentCreate(
        id="schema-agent",
        name="Schema Agent",
        role="analyst",
        system_prompt="Use verified data.",
        model="qwen-32b",
        model_adapter="qwen",
        prompt_template="Analyze {{topic}} for {{time_range}}.",
        model_config={"temperature": 0.2},
        input_schema={
            "topic": {"type": "string", "required": True},
            "time_range": {"type": "string", "required": True},
        },
        output_schema={"summary": "string"},
        status="active",
    )
    assert agent.input_schema["required"] == ["topic", "time_range"]
    assert agent.output_schema["properties"]["summary"]["type"] == "string"
    assert agent.model == "qwen-32b"
    assert agent.model_adapter == "qwen"
    assert agent.prompt_template.startswith("Analyze")


def test_prompt_template_rejects_variables_missing_from_input_schema() -> None:
    with pytest.raises(ValidationError, match="not declared by input_schema"):
        AgentCreate(
            id="schema-agent",
            name="Schema Agent",
            role="analyst",
            system_prompt="Use verified data.",
            prompt_template="Analyze {{unknown}}.",
        )


def test_configuration_update_accepts_model_config_alias() -> None:
    update = AgentConfigurationUpdate(
        system_prompt="Use verified data.",
        model="deepseek-r1",
        prompt_template="{{input}}",
        model_adapter="deepseek",
        model_config={"temperature": 0},
    )
    assert update.model_settings == {"temperature": 0}


def test_legacy_model_config_remains_metadata_and_uses_safe_runtime_default() -> None:
    agent = AgentCreate(
        id="legacy-agent",
        name="Legacy Agent",
        role="analyst",
        system_prompt="Use verified data.",
        model_config={"model": "legacy-qwen"},
    )
    assert agent.model_settings["model"] == "legacy-qwen"
    assert agent.model == "hermes-agent"


def test_public_gateway_supports_v2_envelope_and_legacy_flat_input() -> None:
    request = {"input": {"topic": "AI"}, "stream": True, "session_id": "external-1"}
    assert _public_payload(request) == ({"topic": "AI"}, "stream", "external-1")
    assert _public_payload({"topic": "AI"}) == ({"topic": "AI"}, None, None)


def test_public_gateway_rejects_invalid_v2_envelope_instead_of_treating_it_as_legacy() -> None:
    with pytest.raises(ValidationError):
        _public_payload({"input": {"topic": "AI"}, "stream": False, "unexpected": True})


def test_agent_migration_adds_required_v2_columns_without_plaintext_api_key() -> None:
    migration = Path("backend/alembic/versions/0005_agent_schema_gateway_contract.py").read_text()
    for column in ("model", "prompt_template", "model_adapter", "api_enabled"):
        assert f'Column("{column}"' in migration
    assert 'Column("api_key"' not in migration


def test_hermes_bootstrap_preserves_agent_level_model_names() -> None:
    bootstrap = Path("docker/hermes-init.py").read_text()
    assert '"provider": "custom"' in bootstrap
    assert '"api_key": os.environ["MODEL_GATEWAY_API_KEY"]' in bootstrap
    assert '"provider": "deepseek"' not in bootstrap


@pytest.mark.asyncio
async def test_response_mode_update_does_not_access_configuration_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = SimpleNamespace(response_mode="sync")

    async def get_agent(*args: object) -> object:
        return agent

    async def update_mode(*args: object) -> object:
        agent.response_mode = args[-1]
        return agent

    monkeypatch.setattr(agent_api.repository, "get_agent", get_agent)
    monkeypatch.setattr(agent_api.repository, "update_agent_response_mode", update_mode)
    monkeypatch.setattr(agent_api.AgentRead, "model_validate", lambda value: value)
    result = await agent_api.update_agent_response_mode(
        "schema-agent",
        agent_api.AgentResponseModeUpdate(response_mode="stream"),
        session=object(),  # type: ignore[arg-type]
    )
    assert result.response_mode == "stream"


@pytest.mark.asyncio
async def test_configuration_update_rejects_undeclared_template_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = SimpleNamespace(input_schema={"type": "object", "properties": {"topic": {"type": "string"}}})

    async def get_agent(*args: object) -> object:
        return agent

    monkeypatch.setattr(agent_api.repository, "get_agent", get_agent)
    payload = AgentConfigurationUpdate(
        system_prompt="Use verified data.",
        model="qwen-32b",
        prompt_template="{{unknown}}",
        model_adapter="qwen",
    )
    with pytest.raises(HTTPException) as caught:
        await agent_api.update_agent_configuration(
            "schema-agent",
            payload,
            session=object(),  # type: ignore[arg-type]
        )
    assert caught.value.status_code == 422
