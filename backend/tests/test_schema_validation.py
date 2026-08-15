import pytest

from app.schemas.schema_validation import normalize_schema, parse_and_validate_output, validate_instance


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


def test_schema_normalization_does_not_mutate_the_caller_value() -> None:
    source = {"topic": {"type": "string", "required": True}}
    normalize_schema(source)
    assert source == {"topic": {"type": "string", "required": True}}


def test_validation_reports_multiple_failures_with_paths_and_formats() -> None:
    schema = {
        "type": "object",
        "properties": {
            "count": {"type": "integer", "minimum": 1},
            "email": {"type": "string", "format": "email"},
        },
        "required": ["count", "email"],
    }
    with pytest.raises(ValueError) as caught:
        validate_instance(schema, {"count": 0, "email": "not-an-email"}, label="request")
    assert "at count" in str(caught.value)
    assert "at email" in str(caught.value)


def test_output_parser_accepts_json_fences_and_rejects_invalid_output() -> None:
    schema = normalize_schema({"summary": "string"})
    assert parse_and_validate_output(schema, '```json\n{"summary":"ok"}\n```') == {"summary": "ok"}
    with pytest.raises(ValueError, match="not valid JSON"):
        parse_and_validate_output(schema, "not-json")


def test_full_json_schema_supports_non_object_root_types() -> None:
    schema = normalize_schema({"type": "array", "items": {"type": "string"}, "minItems": 1})
    assert schema["type"] == "array"
    validate_instance(schema, ["a"], label="request")
    with pytest.raises(ValueError, match="non-empty"):
        validate_instance(schema, [], label="request")


def test_shorthand_allows_fields_named_like_schema_annotations() -> None:
    schema = normalize_schema({"description": "string", "type": {"type": "string"}})
    assert schema["properties"]["description"]["type"] == "string"
    assert schema["properties"]["type"]["type"] == "string"
