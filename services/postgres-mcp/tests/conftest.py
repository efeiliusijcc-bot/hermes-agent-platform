from __future__ import annotations

import os

from cryptography.fernet import Fernet


os.environ.setdefault("MCP_GATEWAY_SIGNING_KEY", "postgres-mcp-test-signing-key-that-is-long-enough")
os.environ.setdefault("MODEL_REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
os.environ.setdefault("POSTGRES_USER", "registry")
os.environ.setdefault("POSTGRES_PASSWORD", "registry-password")
os.environ.setdefault("POSTGRES_DB", "registry")
