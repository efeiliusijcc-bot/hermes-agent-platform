from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from app.capabilities.policy import ParameterPolicyError, apply_parameter_policy
from app.capabilities.security import (
    CapabilityTokenError,
    issue_execution_capability_token,
    verify_execution_capability_token,
)
from app.repositories.production import validate_agent_snapshot
from app.runtime.base import RuntimeAdapter
from app.skills.package import SkillLoadError, skill_contract, validate_skill_contract
from app.capabilities.resolver import version_satisfies
from app.config import Settings
from app.main import app


def test_execution_capability_token_binds_version_scope_and_expiry() -> None:
    token = issue_execution_capability_token(
        execution_id="2aa9cb26-53e7-4bbf-a9ea-d65fe8a583c9",
        agent_id="agent-a",
        agent_version_id="7a7b56fb-1b21-4f13-93f0-b5854ca84c49",
        runtime_id="runtime-a",
        allowed_bindings=["binding-b", "binding-a"],
        resolution_digest="sha256:abc",
        now=1000,
    )
    claims = verify_execution_capability_token(token, now=1001)
    assert claims["allowed_bindings"] == ["binding-a", "binding-b"]
    assert claims["resolution_digest"] == "sha256:abc"
    with pytest.raises(CapabilityTokenError, match="expired"):
        verify_execution_capability_token(token, now=2000)
    with pytest.raises(CapabilityTokenError):
        verify_execution_capability_token(f"{token[:-1]}x", now=1001)


def test_parameter_policy_rejects_runtime_owned_fields_and_injects_scope() -> None:
    value = apply_parameter_policy(
        {"query": "hello", "top_k": 20},
        {"maximum": {"top_k": 20}, "fixed": {"tenant": "internal"}},
        {"resource_ids": ["knowledge-a"]},
    )
    assert value["tenant"] == "internal"
    assert value["resource_scope"] == {"resource_ids": ["knowledge-a"]}
    with pytest.raises(ParameterPolicyError, match="forbidden"):
        apply_parameter_policy({"endpoint": "http://evil.test"}, {}, None)
    with pytest.raises(ParameterPolicyError, match="maximum"):
        apply_parameter_policy({"top_k": 50}, {"maximum": {"top_k": 20}}, None)
    with pytest.raises(ParameterPolicyError, match="nested.endpoint"):
        apply_parameter_policy({"nested": {"endpoint": "http://metadata.invalid"}}, {}, None)


def test_skill_contract_accepts_abstract_capability_requirements() -> None:
    manifest = {
        "name": "generic-analysis",
        "version": "1.0.0",
        "spec": {
            "execution_mode": "hybrid",
            "runtime_requirements": {"required_features": ["tool_call"]},
            "capability_requirements": [
                {
                    "alias": "source_search",
                    "capability": "knowledge.search",
                    "version": ">=1.0.0 <2.0.0",
                    "required": True,
                    "failure_policy": "fail_closed",
                }
            ],
        },
    }
    validate_skill_contract(manifest)
    features, requirements, mode = skill_contract(manifest)
    assert features == ["tool_call"]
    assert requirements[0]["capability"] == "knowledge.search"
    assert mode == "hybrid"


def test_skill_contract_rejects_plaintext_credentials() -> None:
    manifest = {
        "name": "unsafe-skill",
        "version": "1.0.0",
        "api_key": "must-not-be-here",
    }
    with pytest.raises(SkillLoadError, match="plaintext credential"):
        validate_skill_contract(manifest)


def test_snapshot_v1_and_v2_are_compatible() -> None:
    base = {
        "format_version": 1,
        "prompt": {"system_prompt": "Do work", "prompt_template": "{{input}}"},
        "model": {"name": "test-model", "adapter": "hermes", "config": {}},
        "skill_ids": [],
        "mcp_ids": [],
        "schema": {"input_schema": {}, "output_schema": {}},
        "runtime": {
            "response_mode": "sync",
            "runtime_type": "hermes",
            "runtime_id": None,
            "runtime_config": {},
            "capability_profile": {},
        },
    }
    validate_agent_snapshot(base)
    version_two = deepcopy(base)
    version_two.update(
        {
            "format_version": 2,
            "skills": [],
            "capability_bindings": [],
            "resource_scope_revisions": [],
            "policy_set_revisions": [],
            "resolution_digest": "sha256:abc",
        }
    )
    version_two["runtime"]["required_features"] = []
    validate_agent_snapshot(version_two)


def test_capability_semver_range() -> None:
    assert version_satisfies("1.4.2", ">=1.0.0 <2.0.0")
    assert not version_satisfies("2.0.0", ">=1.0.0 <2.0.0")
    assert not version_satisfies("1.4.2", "not-a-range")


def test_platform_runtimes_with_hidden_token_dispatchers_advertise_capability_gateway() -> None:
    pi = RuntimeAdapter.describe_features(SimpleNamespace(runtime_type="pi"))
    hermes = RuntimeAdapter.describe_features(SimpleNamespace(runtime_type="hermes"))
    deepseek = RuntimeAdapter.describe_features(SimpleNamespace(runtime_type="deepseek"))
    assert pi.features["capability_gateway"] is True
    assert hermes.features["capability_gateway"] is True
    assert deepseek.features["capability_gateway"] is True


def test_control_plane_has_no_browser_unlock_contract() -> None:
    assert "platform_management_api_key" not in Settings.model_fields
    assert "X-Platform-Management-Key" not in json.dumps(app.openapi())
