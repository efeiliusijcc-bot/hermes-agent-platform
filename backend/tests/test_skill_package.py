from __future__ import annotations

import io
import zipfile

import pytest

from app.config import get_settings
from app.skills import SkillLoadError, SkillPackageImporter


def package(entries: dict[str, str], *, symlink: str | None = None) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.create_system = 3
            info.external_attr = 0o120777 << 16
            archive.writestr(info, "../outside")
    return stream.getvalue()


def package_with_duplicate(name: str, first: str, second: str) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(name, first)
        archive.writestr(name.upper(), second)
    return stream.getvalue()


@pytest.fixture(autouse=True)
def settings(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("SKILLS_ROOT", str(tmp_path / "skills"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_imports_phase2_manifest_and_generates_runtime_config(tmp_path) -> None:
    imported = SkillPackageImporter().import_zip(
        package(
            {
                "knowledge-analysis/skill.yaml": (
                    "name: knowledge-analysis\nversion: 1.0.0\n"
                    "description: 企业知识分析能力\nentry: SKILL.md\ntools:\n  - database-query\n"
                ),
                "knowledge-analysis/SKILL.md": "# Knowledge Analysis\n\nAnalyze reliable evidence.",
                "knowledge-analysis/prompts/example.md": "Prompt",
            }
        )
    )

    assert imported.id == "knowledge-analysis"
    assert imported.version == "1.0.0"
    installed = tmp_path / "skills" / "knowledge-analysis"
    assert (installed / "SKILL.md").is_file()
    assert "id: knowledge-analysis" in (installed / "config.yaml").read_text()


@pytest.mark.parametrize(
    "payload, message",
    [
        (package({"../skill.yaml": "name: bad"}), "unsafe archive path"),
        (package({"skill.yaml": "name: safe-skill\nversion: 1.0.0", "SKILL.md": "ok"}, symlink="link"), "symbolic links"),
        (package({"SKILL.md": "missing manifest"}), "skill.yaml"),
        (package_with_duplicate("skill.yaml", "name: safe-skill", "name: other-skill"), "duplicate archive path"),
    ],
)
def test_rejects_unsafe_or_invalid_packages(payload: bytes, message: str) -> None:
    with pytest.raises(SkillLoadError, match=message):
        SkillPackageImporter().import_zip(payload)
