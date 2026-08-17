import json
from types import SimpleNamespace

import pytest

from app.api.agents import _skill_output_schema
from app.skills import SkillLoadError
from app.skills import loader as loader_module
from app.skills.loader import LoadedSkill, SkillLoader


def _loader(monkeypatch: pytest.MonkeyPatch, tmp_path) -> SkillLoader:
    monkeypatch.setattr(
        loader_module,
        "get_settings",
        lambda: SimpleNamespace(skills_root=str(tmp_path), skill_max_document_bytes=1024 * 1024),
    )
    return SkillLoader()


def test_loader_reads_manifest_output_schema(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    skill_dir = tmp_path / "write-hb"
    schema_dir = skill_dir / "schemas"
    schema_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("Return strict JSON.", encoding="utf-8")
    (skill_dir / "config.yaml").write_text("id: write-hb\n", encoding="utf-8")
    expected = {
        "type": "object",
        "required": ["status"],
        "properties": {"status": {"const": "completed"}},
    }
    (schema_dir / "output.schema.json").write_text(json.dumps(expected), encoding="utf-8")

    loaded = _loader(monkeypatch, tmp_path).load_definition(
        skill_id="write-hb",
        name="write-hb",
        relative_path="write-hb",
        manifest={"schemas": {"output": "schemas/output.schema.json"}},
    )

    assert loaded.output_schema == expected
    assert _skill_output_schema([loaded]) == expected


def test_loader_rejects_output_schema_path_escape(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    skill_dir = tmp_path / "write-hb"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("Return strict JSON.", encoding="utf-8")
    (skill_dir / "config.yaml").write_text("id: write-hb\n", encoding="utf-8")
    (tmp_path / "outside.json").write_text('{"type":"object"}', encoding="utf-8")

    with pytest.raises(SkillLoadError, match="escapes the skill directory"):
        _loader(monkeypatch, tmp_path).load_definition(
            skill_id="write-hb",
            name="write-hb",
            relative_path="write-hb",
            manifest={"schemas": {"output": "../outside.json"}},
        )


def test_conflicting_skill_output_schemas_require_agent_schema() -> None:
    skills = [
        LoadedSkill("one", "one", "one", {}, {"type": "string"}),
        LoadedSkill("two", "two", "two", {}, {"type": "object"}),
    ]

    with pytest.raises(SkillLoadError, match="multiple bound Skills"):
        _skill_output_schema(skills)
