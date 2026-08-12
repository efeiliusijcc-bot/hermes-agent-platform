import os

os.environ.setdefault("POSTGRES_PASSWORD", "test-postgres-password")
os.environ.setdefault("REDIS_PASSWORD", "test-redis-password")
os.environ.setdefault("HERMES_API_KEY", "test-hermes-api-key")
os.environ.setdefault("MCP_GATEWAY_SIGNING_KEY", "test-mcp-signing-key-that-is-long-enough")
