from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID


AGENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")


class WorkspaceBoundaryError(ValueError):
    pass


@dataclass(frozen=True)
class SessionWorkspace:
    root: Path
    input: Path
    output: Path
    temp: Path
    workspace_type: str = "document"
    repository: Path | None = None


class WorkspaceManager:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def create_session(
        self,
        agent_id: str,
        session_id: UUID,
        *,
        workspace_type: str = "document",
    ) -> SessionWorkspace:
        if not AGENT_ID.fullmatch(agent_id):
            raise WorkspaceBoundaryError("invalid Agent id for workspace")
        if workspace_type not in {"document", "repository"}:
            raise WorkspaceBoundaryError("workspace type must be document or repository")
        session_name = str(session_id)
        agent_root = self._inside(self.root / agent_id)
        sessions_root = self._inside(agent_root / "sessions")
        target = self._inside(sessions_root / session_name)
        input_path = self._inside(target / "input")
        output_path = self._inside(target / "output")
        temp_path = self._inside(target / "temp")
        repository_path = self._inside(target / "repository") if workspace_type == "repository" else None
        paths = [agent_root, sessions_root, target, input_path, output_path, temp_path]
        if repository_path is not None:
            paths.append(repository_path)
        for path in paths:
            path.mkdir(parents=True, exist_ok=True, mode=0o770)
            path.chmod(0o2770)
        return SessionWorkspace(
            root=target,
            input=input_path,
            output=output_path,
            temp=temp_path,
            workspace_type=workspace_type,
            repository=repository_path,
        )

    def write_output(self, workspace: SessionWorkspace, filename: str, content: bytes) -> Path:
        if not SAFE_FILENAME.fullmatch(filename) or filename in {".", ".."}:
            raise WorkspaceBoundaryError("artifact filename must be a single safe path component")
        output_root = self._inside(workspace.output)
        target = self._inside(output_root / filename)
        try:
            target.relative_to(output_root)
        except ValueError as exc:
            raise WorkspaceBoundaryError("artifact path escapes the Session output directory") from exc
        temporary = target.with_name(f".{target.name}.tmp")
        temporary.write_bytes(content)
        temporary.chmod(0o660)
        temporary.replace(target)
        return target

    def write_input(self, workspace: SessionWorkspace, filename: str, content: bytes) -> Path:
        if not SAFE_FILENAME.fullmatch(filename) or filename in {".", ".."}:
            raise WorkspaceBoundaryError("input filename must be a single safe path component")
        input_root = self._inside(workspace.input)
        target = self._inside(input_root / filename)
        try:
            target.relative_to(input_root)
        except ValueError as exc:
            raise WorkspaceBoundaryError("input path escapes the Session input directory") from exc
        temporary = target.with_name(f".{target.name}.tmp")
        temporary.write_bytes(content)
        temporary.chmod(0o660)
        temporary.replace(target)
        return target

    def resolve_registered(self, relative_path: str) -> Path:
        candidate = Path(relative_path)
        if candidate.is_absolute():
            raise WorkspaceBoundaryError("registered artifact path must be relative")
        resolved = self._inside(self.root / candidate)
        if not resolved.is_file():
            raise FileNotFoundError("artifact file does not exist")
        return resolved

    def relative(self, path: Path) -> str:
        resolved = self._inside(path)
        return resolved.relative_to(self.root).as_posix()

    def _inside(self, path: Path) -> Path:
        resolved = path.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceBoundaryError("path escapes the workspace root") from exc
        return resolved
