from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class ModelSecretError(RuntimeError):
    pass


class ModelSecretCipher:
    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.strip().encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise ModelSecretError(
                "MODEL_REGISTRY_ENCRYPTION_KEY must be a URL-safe base64 Fernet key"
            ) from exc

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
            raise ModelSecretError("stored model credential cannot be decrypted") from exc
