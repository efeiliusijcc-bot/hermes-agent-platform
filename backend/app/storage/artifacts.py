from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Protocol
from uuid import UUID

from minio import Minio
from minio.error import S3Error

from app.config import Settings, get_settings


SAFE_AGENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")


class ArtifactStorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredArtifact:
    storage_type: str
    storage_path: str
    content: bytes
    sha256: str

    @property
    def size_bytes(self) -> int:
        return len(self.content)


class StorageProvider(Protocol):
    storage_type: str

    async def save(self, path: str, content: bytes, content_type: str) -> None: ...
    async def get(self, path: str) -> bytes: ...
    async def delete(self, path: str) -> None: ...
    async def exists(self, path: str) -> bool: ...
    async def ping(self) -> None: ...


class FilesystemStorageProvider:
    def __init__(self, root: str | Path, *, storage_type: str) -> None:
        self.root = Path(root).resolve()
        self.storage_type = storage_type

    async def save(self, path: str, content: bytes, content_type: str) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o770)
        temporary = target.with_name(f".{target.name}.tmp")
        temporary.write_bytes(content)
        temporary.chmod(0o660)
        temporary.replace(target)

    async def get(self, path: str) -> bytes:
        target = self._resolve(path)
        try:
            return target.read_bytes()
        except FileNotFoundError as exc:
            raise ArtifactStorageError("artifact object does not exist") from exc

    async def delete(self, path: str) -> None:
        target = self._resolve(path)
        try:
            target.unlink()
        except FileNotFoundError:
            return

    async def exists(self, path: str) -> bool:
        return self._resolve(path).is_file()

    async def ping(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o770)
        if not self.root.is_dir():
            raise ArtifactStorageError("artifact filesystem root is unavailable")

    def _resolve(self, path: str) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            raise ArtifactStorageError("artifact storage path must be relative")
        resolved = (self.root / candidate).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ArtifactStorageError("artifact storage path escapes provider root") from exc
        return resolved


class MinIOStorageProvider:
    storage_type = "minio"

    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.artifact_minio_bucket
        self.client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_root_user,
            secret_key=settings.minio_root_password.get_secret_value(),
            secure=settings.minio_secure,
        )

    async def save(self, path: str, content: bytes, content_type: str) -> None:
        try:
            await asyncio.to_thread(
                self.client.put_object,
                self.bucket,
                path,
                BytesIO(content),
                len(content),
                content_type=content_type,
            )
        except Exception as exc:
            raise ArtifactStorageError("artifact could not be saved to MinIO") from exc

    async def get(self, path: str) -> bytes:
        response = None
        try:
            response = await asyncio.to_thread(self.client.get_object, self.bucket, path)
            return await asyncio.to_thread(response.read)
        except Exception as exc:
            raise ArtifactStorageError("artifact object is unavailable in MinIO") from exc
        finally:
            if response is not None:
                response.close()
                response.release_conn()

    async def delete(self, path: str) -> None:
        try:
            await asyncio.to_thread(self.client.remove_object, self.bucket, path)
        except Exception as exc:
            raise ArtifactStorageError("artifact object could not be deleted from MinIO") from exc

    async def exists(self, path: str) -> bool:
        try:
            await asyncio.to_thread(self.client.stat_object, self.bucket, path)
            return True
        except Exception as exc:
            if isinstance(exc, S3Error) and exc.code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
                return False
            raise ArtifactStorageError("artifact object status could not be read from MinIO") from exc

    async def ping(self) -> None:
        try:
            exists = await asyncio.to_thread(self.client.bucket_exists, self.bucket)
            if not exists:
                await asyncio.to_thread(self.client.make_bucket, self.bucket)
        except Exception as exc:
            raise ArtifactStorageError("artifact MinIO bucket is unavailable") from exc


class ArtifactStorage:
    def __init__(self, provider: StorageProvider, *, max_bytes: int) -> None:
        self.provider = provider
        self.max_bytes = max_bytes

    @property
    def storage_type(self) -> str:
        return self.provider.storage_type

    async def save(
        self,
        *,
        agent_id: str,
        session_id: UUID,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> StoredArtifact:
        path = self._path(agent_id, session_id, filename)
        if len(content) > self.max_bytes:
            raise ArtifactStorageError("artifact exceeds the configured size limit")
        await self.provider.save(path, content, content_type)
        return StoredArtifact(
            storage_type=self.storage_type,
            storage_path=path,
            content=content,
            sha256=hashlib.sha256(content).hexdigest(),
        )

    async def get(self, path: str, *, expected_sha256: str | None = None) -> bytes:
        content = await self.provider.get(path)
        if len(content) > self.max_bytes:
            raise ArtifactStorageError("stored artifact exceeds the configured size limit")
        if expected_sha256 and not hashlib.sha256(content).hexdigest() == expected_sha256:
            raise ArtifactStorageError("artifact integrity check failed")
        return content

    async def delete(self, path: str) -> None:
        await self.provider.delete(path)

    async def exists(self, path: str) -> bool:
        return await self.provider.exists(path)

    async def ping(self) -> None:
        await self.provider.ping()

    @staticmethod
    def _path(agent_id: str, session_id: UUID, filename: str) -> str:
        if not SAFE_AGENT_ID.fullmatch(agent_id):
            raise ArtifactStorageError("invalid Agent id for artifact storage")
        if not SAFE_FILENAME.fullmatch(filename) or filename in {".", ".."}:
            raise ArtifactStorageError("artifact filename must be a single safe path component")
        return f"{agent_id}/{session_id}/{filename}"


@lru_cache
def get_artifact_storage(storage_type: str | None = None) -> ArtifactStorage:
    settings = get_settings()
    selected = storage_type or settings.artifact_storage_provider
    if selected == "minio":
        provider: StorageProvider = MinIOStorageProvider(settings)
    elif selected == "nas":
        provider = FilesystemStorageProvider(settings.artifact_nas_root, storage_type="nas")
    elif selected == "workspace":
        provider = FilesystemStorageProvider(settings.workspace_root, storage_type="workspace")
    elif selected == "local":
        provider = FilesystemStorageProvider(settings.artifact_local_root, storage_type="local")
    else:
        raise ArtifactStorageError(f"unsupported artifact storage provider: {selected}")
    return ArtifactStorage(provider, max_bytes=settings.artifact_max_bytes)
