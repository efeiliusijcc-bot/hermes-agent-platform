from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from app.config import get_settings
from app.skills.loader import SkillLoadError, SkillLoader


SKILL_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
VERSION = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+-]{0,63}$")


@dataclass(frozen=True)
class ImportedSkill:
    id: str
    name: str
    description: str | None
    version: str
    path: str
    manifest: dict[str, Any]
    runtime_support: tuple[str, ...]
    package_sha256: str


class SkillPackageImporter:
    def __init__(self, root: Path | None = None) -> None:
        settings = get_settings()
        self.root = (root or Path(settings.skills_root)).resolve()
        self.max_upload_bytes = settings.skill_max_upload_bytes
        self.max_extracted_bytes = settings.skill_max_extracted_bytes
        self.max_entries = settings.skill_max_archive_entries

    def import_zip(self, package: bytes) -> ImportedSkill:
        if not package:
            raise SkillLoadError("Skill ZIP is empty")
        if len(package) > self.max_upload_bytes:
            raise SkillLoadError(f"Skill ZIP exceeds {self.max_upload_bytes} bytes")
        package_sha256 = hashlib.sha256(package).hexdigest()
        self.root.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix=".skill-upload-", dir=self.root) as temporary:
            stage = Path(temporary)
            archive_path = stage / "skill.zip"
            archive_path.write_bytes(package)
            extract_root = stage / "extracted"
            extract_root.mkdir()
            self._extract(archive_path, extract_root)
            package_root = self._package_root(extract_root)
            manifest = self._read_manifest(package_root)
            skill_id, name, description, version, entry, runtime_support = self._validate_manifest(manifest)
            validate_skill_contract(manifest)
            self._normalize_runtime_files(
                package_root, skill_id, name, description, version, entry, manifest, runtime_support
            )

            destination = self.root / skill_id
            if destination.exists():
                raise FileExistsError(f"skill path already exists: {skill_id}")
            installed = stage / "installed"
            shutil.copytree(package_root, installed, symlinks=False)
            os.replace(installed, destination)
            try:
                SkillLoader().load_definition(skill_id=skill_id, name=name, relative_path=skill_id)
            except Exception:
                shutil.rmtree(destination, ignore_errors=True)
                raise

        return ImportedSkill(
            id=skill_id,
            name=name,
            description=description,
            version=version,
            path=skill_id,
            manifest=manifest,
            runtime_support=runtime_support,
            package_sha256=package_sha256,
        )

    def remove(self, relative_path: str) -> None:
        resolved = self.validate_managed_path(relative_path)
        if resolved.is_dir():
            shutil.rmtree(resolved)

    def remove_staged(self, path: Path) -> None:
        resolved = path.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise SkillLoadError("staged Skill path escapes SKILLS_ROOT") from exc
        if resolved.name.startswith(".") and resolved.name.endswith(".deleting") and resolved.is_dir():
            shutil.rmtree(resolved)

    def validate_managed_path(self, relative_path: str) -> Path:
        path = Path(relative_path)
        if path.is_absolute() or len(path.parts) != 1 or not SKILL_ID.fullmatch(path.name):
            raise SkillLoadError("only managed uploaded Skill paths can be removed")
        resolved = (self.root / path).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise SkillLoadError("skill path escapes SKILLS_ROOT") from exc
        return resolved

    def _extract(self, archive_path: Path, extract_root: Path) -> None:
        try:
            with zipfile.ZipFile(archive_path) as archive:
                entries = archive.infolist()
                if not entries or len(entries) > self.max_entries:
                    raise SkillLoadError(f"Skill ZIP must contain 1 to {self.max_entries} entries")
                total_bytes = 0
                extracted_bytes = 0
                seen: set[str] = set()
                for info in entries:
                    normalized = info.filename.replace("\\", "/")
                    path = PurePosixPath(normalized)
                    if (
                        not normalized
                        or normalized.startswith("/")
                        or path.is_absolute()
                        or ".." in path.parts
                        or "" in path.parts
                    ):
                        raise SkillLoadError(f"unsafe archive path: {info.filename}")
                    canonical = "/".join(path.parts).rstrip("/")
                    canonical_key = canonical.casefold()
                    if canonical_key in seen:
                        raise SkillLoadError(f"duplicate archive path: {canonical}")
                    seen.add(canonical_key)
                    file_type = (info.external_attr >> 16) & 0o170000
                    if file_type == stat.S_IFLNK:
                        raise SkillLoadError(f"symbolic links are not allowed: {canonical}")
                    if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
                        raise SkillLoadError(f"special files are not allowed: {canonical}")
                    total_bytes += info.file_size
                    if total_bytes > self.max_extracted_bytes:
                        raise SkillLoadError(f"Skill ZIP expands beyond {self.max_extracted_bytes} bytes")
                    target = extract_root.joinpath(*path.parts)
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, target.open("xb") as destination:
                        while chunk := source.read(64 * 1024):
                            extracted_bytes += len(chunk)
                            if extracted_bytes > self.max_extracted_bytes:
                                raise SkillLoadError(
                                    f"Skill ZIP expands beyond {self.max_extracted_bytes} bytes"
                                )
                            destination.write(chunk)
        except zipfile.BadZipFile as exc:
            raise SkillLoadError("uploaded file is not a valid ZIP archive") from exc

    def _package_root(self, extract_root: Path) -> Path:
        children = [item for item in extract_root.iterdir() if item.name != "__MACOSX"]
        if len(children) == 1 and children[0].is_dir():
            return children[0]
        return extract_root

    @staticmethod
    def _read_manifest(package_root: Path) -> dict[str, Any]:
        manifest_path = package_root / "skill.yaml"
        if not manifest_path.is_file():
            raise SkillLoadError("Skill ZIP must contain skill.yaml")
        try:
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise SkillLoadError(f"skill.yaml could not be read: {exc}") from exc
        if not isinstance(manifest, dict):
            raise SkillLoadError("skill.yaml must contain an object")
        return manifest

    @staticmethod
    def _validate_manifest(
        manifest: dict[str, Any],
    ) -> tuple[str, str, str | None, str, str, tuple[str, ...]]:
        raw_id = manifest.get("id", manifest.get("name"))
        raw_name = manifest.get("display_name", manifest.get("name"))
        raw_version = manifest.get("version")
        raw_description = manifest.get("description")
        raw_entry_value = manifest.get("entry", "SKILL.md")
        raw_entry = raw_entry_value.get("file") if isinstance(raw_entry_value, dict) else raw_entry_value
        raw_runtime_support = manifest.get("runtime_support", ["hermes"])
        if not isinstance(raw_id, str) or not SKILL_ID.fullmatch(raw_id):
            raise SkillLoadError("skill.yaml id/name must be a lowercase hyphenated identifier")
        if not isinstance(raw_name, str) or not raw_name.strip() or len(raw_name) > 255:
            raise SkillLoadError("skill.yaml name/display_name must contain 1 to 255 characters")
        if not isinstance(raw_version, str) or not VERSION.fullmatch(raw_version):
            raise SkillLoadError("skill.yaml version is required and invalid")
        if raw_description is not None and not isinstance(raw_description, str):
            raise SkillLoadError("skill.yaml description must be a string")
        if raw_entry != "SKILL.md":
            raise SkillLoadError("first-stage Skill entry must be SKILL.md")
        if (
            not isinstance(raw_runtime_support, list)
            or not raw_runtime_support
            or any(item not in {"hermes", "pi", "deepseek"} for item in raw_runtime_support)
        ):
            raise SkillLoadError(
                "skill.yaml runtime_support must contain hermes, pi, and/or deepseek"
            )
        runtime_support = tuple(dict.fromkeys(str(item) for item in raw_runtime_support))
        return raw_id, raw_name.strip(), raw_description, raw_version, raw_entry, runtime_support

    @staticmethod
    def _normalize_runtime_files(
        package_root: Path,
        skill_id: str,
        name: str,
        description: str | None,
        version: str,
        entry: str,
        manifest: dict[str, Any],
        runtime_support: tuple[str, ...],
    ) -> None:
        if not (package_root / entry).is_file():
            raise SkillLoadError(f"Skill ZIP entry does not exist: {entry}")
        config_path = package_root / "config.yaml"
        if config_path.exists():
            try:
                config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, yaml.YAMLError) as exc:
                raise SkillLoadError(f"config.yaml could not be read: {exc}") from exc
            if not isinstance(config, dict):
                raise SkillLoadError("config.yaml must contain an object")
            if config.get("id") not in {None, skill_id}:
                raise SkillLoadError("config.yaml id does not match skill.yaml")
        else:
            config = {}
        config.update(
            {
                "id": skill_id,
                "name": name,
                "description": description,
                "version": version,
                "entry": entry,
                "tools": manifest.get("tools", []),
                "runtime_support": list(runtime_support),
            }
        )
        config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")


def validate_skill_contract(manifest: dict[str, Any]) -> None:
    spec = manifest.get("spec") if isinstance(manifest.get("spec"), dict) else manifest
    execution_mode = spec.get("execution_mode", "autonomous")
    if execution_mode not in {"autonomous", "workflow", "hybrid"}:
        raise SkillLoadError("skill.yaml execution_mode must be autonomous, workflow, or hybrid")
    runtime_requirements = spec.get("runtime_requirements", {})
    if not isinstance(runtime_requirements, dict):
        raise SkillLoadError("skill.yaml runtime_requirements must be an object")
    required_features = runtime_requirements.get("required_features", [])
    if not isinstance(required_features, list) or any(
        not isinstance(item, str) or not item.strip() for item in required_features
    ):
        raise SkillLoadError("skill.yaml required_features must be a string array")
    requirements = spec.get("capability_requirements", [])
    if not isinstance(requirements, list):
        raise SkillLoadError("skill.yaml capability_requirements must be an array")
    aliases: set[str] = set()
    for index, requirement in enumerate(requirements):
        if not isinstance(requirement, dict):
            raise SkillLoadError(f"capability_requirements[{index}] must be an object")
        alias = requirement.get("alias")
        capability = requirement.get("capability")
        version_range = requirement.get("version", "*")
        if not isinstance(alias, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,127}", alias):
            raise SkillLoadError(f"capability_requirements[{index}].alias is invalid")
        if alias in aliases:
            raise SkillLoadError(f"duplicate capability requirement alias: {alias}")
        aliases.add(alias)
        if not isinstance(capability, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{1,254}", capability):
            raise SkillLoadError(f"capability_requirements[{index}].capability is invalid")
        if not isinstance(version_range, str) or not version_range.strip():
            raise SkillLoadError(f"capability_requirements[{index}].version is invalid")
        if requirement.get("failure_policy", "fail_closed") not in {
            "fail_closed",
            "continue_with_warning",
        }:
            raise SkillLoadError(f"capability_requirements[{index}].failure_policy is invalid")
        minimum_calls = requirement.get("minimum_calls", 0)
        if isinstance(minimum_calls, bool) or not isinstance(minimum_calls, int) or minimum_calls < 0:
            raise SkillLoadError(f"capability_requirements[{index}].minimum_calls is invalid")
    _reject_plaintext_secrets(manifest)


def skill_contract(manifest: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]], str]:
    spec = manifest.get("spec") if isinstance(manifest.get("spec"), dict) else manifest
    runtime = spec.get("runtime_requirements") if isinstance(spec.get("runtime_requirements"), dict) else {}
    required_features = [str(item) for item in runtime.get("required_features", [])]
    requirements = [dict(item) for item in spec.get("capability_requirements", []) if isinstance(item, dict)]
    return required_features, requirements, str(spec.get("execution_mode") or "autonomous")


def _reject_plaintext_secrets(value: Any, path: str = "skill.yaml") -> None:
    sensitive = {"api_key", "token", "password", "secret", "private_key", "connection_string"}
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in sensitive and item is not None and item != "" and item != "${CREDENTIAL_REF}":
                raise SkillLoadError(f"{path}.{key} must not contain a plaintext credential")
            _reject_plaintext_secrets(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_plaintext_secrets(item, f"{path}[{index}]")
