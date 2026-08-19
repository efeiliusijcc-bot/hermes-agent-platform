import os
from cryptography.fernet import Fernet

os.environ.setdefault("POSTGRES_PASSWORD", "test-postgres-password")
os.environ.setdefault("REDIS_PASSWORD", "test-redis-password")
os.environ.setdefault("MINIO_ROOT_PASSWORD", "test-minio-password")
os.environ.setdefault("HERMES_API_KEY", "test-hermes-api-key")
os.environ.setdefault("MCP_GATEWAY_SIGNING_KEY", "test-mcp-signing-key-that-is-long-enough")
os.environ.setdefault("MODEL_ENDPOINT", "http://model.test/v1")
os.environ.setdefault("MODEL_API_KEY", "test-model-api-key")
os.environ.setdefault("MODEL_NAME", "test-model")
os.environ.setdefault("MODEL_GATEWAY_API_KEY", "test-model-gateway-api-key")
os.environ.setdefault("MODEL_REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
os.environ.setdefault("ARTIFACT_STORAGE_PROVIDER", "local")
os.environ.setdefault("ARTIFACT_LOCAL_ROOT", "/tmp/hermes-agent-test-artifacts")
