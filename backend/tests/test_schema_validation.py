import pytest

from app.schemas.schema_validation import normalize_schema, validate_instance


def test_normalizes_phase2_shorthand_and_validates_required_input() -> None:
    schema = normalize_schema(
        {
            "topic": {"type": "string", "required": True},
            "limit": {"type": "integer"},
        }
    )
    assert schema["required"] == ["topic"]
    validate_instance(schema, {"topic": "AI", "limit": 3}, label="request")
    with pytest.raises(ValueError, match="required property"):
        validate_instance(schema, {"limit": 3}, label="request")


def test_normalizes_phase2_output_shorthand() -> None:
    schema = normalize_schema({"summary": "string", "recommendations": "array"})
    validate_instance(schema, {"summary": "ok", "recommendations": []}, label="Agent output")
    with pytest.raises(ValueError, match="not of type 'array'"):
        validate_instance(schema, {"summary": "ok", "recommendations": "bad"}, label="Agent output")
