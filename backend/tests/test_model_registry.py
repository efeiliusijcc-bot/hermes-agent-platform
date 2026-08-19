from __future__ import annotations

from datetime import datetime, timezone
from inspect import signature

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.api.model_registrations import (
    create_model,
    delete_model,
    set_default_model,
    test_model as run_model_connectivity_test,
    update_model,
)
from app.db.models import ModelRegistration
from app.model_secrets import ModelSecretCipher, ModelSecretError
from app.schemas.model_registration import ModelRegistrationCreate, ModelRegistrationRead


def test_model_api_key_is_encrypted_and_wrong_master_key_fails() -> None:
    first = ModelSecretCipher(Fernet.generate_key().decode("ascii"))
    second = ModelSecretCipher(Fernet.generate_key().decode("ascii"))
    ciphertext = first.encrypt("upstream-secret")

    assert "upstream-secret" not in ciphertext
    assert first.decrypt(ciphertext) == "upstream-secret"
    with pytest.raises(ModelSecretError):
        second.decrypt(ciphertext)


def test_model_read_contract_never_contains_ciphertext_or_api_key() -> None:
    now = datetime.now(timezone.utc)
    value = ModelRegistration(
        id="report-model",
        display_name="报告模型",
        provider="qwen",
        adapter="qwen",
        base_url="http://model.internal/v1",
        upstream_model="qwen-32b",
        api_key_ciphertext="encrypted-value",
        is_enabled=True,
        is_default=True,
        timeout_seconds=180,
        max_retries=2,
        status="unknown",
        created_at=now,
        updated_at=now,
    )

    payload = ModelRegistrationRead.model_validate(value).model_dump()
    assert payload["api_key_configured"] is True
    assert "api_key" not in payload
    assert "api_key_ciphertext" not in payload
    assert "encrypted-value" not in str(payload)


def test_model_endpoint_rejects_embedded_credentials() -> None:
    with pytest.raises(ValidationError):
        ModelRegistrationCreate(
            id="report-model",
            display_name="报告模型",
            base_url="https://user:password@model.internal/v1",
            upstream_model="qwen-32b",
        )


def test_model_mutations_do_not_accept_a_dedicated_management_key() -> None:
    for handler in (
        create_model,
        update_model,
        set_default_model,
        run_model_connectivity_test,
        delete_model,
    ):
        assert "management_key" not in signature(handler).parameters
