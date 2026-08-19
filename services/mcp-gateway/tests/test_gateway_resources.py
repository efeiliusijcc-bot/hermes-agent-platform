from __future__ import annotations

import os
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("MCP_GATEWAY_SIGNING_KEY", "test-signing-key-that-is-at-least-32-chars")

from hermes_mcp_gateway import auth, capability_gateway, server


class JsonObjectTests(unittest.TestCase):
    def test_rejects_noncanonical_base64url_token_segments(self) -> None:
        self.assertEqual(auth._base64url_decode("YQ"), b"a")
        with self.assertRaises(ValueError):
            auth._base64url_decode("YR")

    def test_normalizes_asyncpg_json_text(self) -> None:
        self.assertEqual(capability_gateway._json_object('{"quota_policy":{"calls_per_minute":5}}'), {
            "quota_policy": {"calls_per_minute": 5}
        })
        self.assertEqual(capability_gateway._json_object({"ready": True}), {"ready": True})
        self.assertEqual(capability_gateway._json_object("[]"), {})
        self.assertEqual(capability_gateway._json_object("not-json"), {})

    def test_cache_key_is_deterministic_and_scope_isolated(self) -> None:
        binding = {
            "id": "binding-a",
            "capability_key": "knowledge.search",
            "capability_version": "1.0.0",
            "resource_scope_revision_id": "scope-a",
            "side_effect": "READ_ONLY",
            "cache_policy": '{"enabled":true,"ttl_seconds":90}',
        }
        implementation = {"connector_instance_revision_id": "connector-r1"}
        claims = {"agent_id": "agent-a"}
        first = capability_gateway._cache_key(
            binding,
            implementation,
            claims,
            {"query": "hello", "filters": {"year": 2026}},
        )
        reordered = capability_gateway._cache_key(
            binding,
            implementation,
            claims,
            {"filters": {"year": 2026}, "query": "hello"},
        )
        self.assertEqual(first, reordered)
        self.assertEqual(capability_gateway._cache_ttl(binding), 90)

        other_scope = {**binding, "resource_scope_revision_id": "scope-b"}
        self.assertNotEqual(
            first,
            capability_gateway._cache_key(
                other_scope,
                implementation,
                claims,
                {"query": "hello", "filters": {"year": 2026}},
            ),
        )
        self.assertNotEqual(
            first,
            capability_gateway._cache_key(
                binding,
                implementation,
                {"agent_id": "agent-b"},
                {"query": "hello", "filters": {"year": 2026}},
            ),
        )


class GatewayResourceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        server.DATABASE_POOL = None
        server.REDIS_CLIENT = None

    async def asyncTearDown(self) -> None:
        server.DATABASE_POOL = None
        server.REDIS_CLIENT = None

    async def test_process_resources_are_reused_and_closed_once(self) -> None:
        pool = AsyncMock()
        redis_client = AsyncMock()
        with (
            patch.object(server.asyncpg, "create_pool", AsyncMock(return_value=pool)) as create_pool,
            patch.object(server.redis, "Redis", return_value=redis_client) as create_redis,
        ):
            first = await server._ensure_resources()
            second = await server._ensure_resources()

            self.assertIs(first[0], pool)
            self.assertIs(first[1], redis_client)
            self.assertEqual(first, second)
            create_pool.assert_awaited_once()
            create_redis.assert_called_once()

            await server._close_resources()
            pool.close.assert_awaited_once()
            redis_client.aclose.assert_awaited_once()
            self.assertIsNone(server.DATABASE_POOL)
            self.assertIsNone(server.REDIS_CLIENT)


class GatewayPolicyTests(unittest.IsolatedAsyncioTestCase):
    def test_runtime_cannot_override_gateway_owned_fields(self) -> None:
        with self.assertRaises(capability_gateway.GatewayError) as denied:
            capability_gateway._apply_policy(
                {"query": "hello", "nested": {"credential_ref": "forged"}},
                {},
                None,
            )
        self.assertEqual(denied.exception.code, "PERMISSION_DENIED")

    async def test_metadata_address_is_rejected_after_dns_resolution(self) -> None:
        resolved = [(2, 1, 6, "", ("169.254.169.254", 80))]
        with patch.object(capability_gateway.socket, "getaddrinfo", return_value=resolved):
            with self.assertRaises(capability_gateway.GatewayError) as denied:
                await capability_gateway._validate_network(
                    "http://metadata.internal/latest",
                    "internal",
                    {},
                )
        self.assertEqual(denied.exception.code, "PERMISSION_DENIED")

    async def test_postgresql_mcp_receives_authority_only_in_internal_headers(self) -> None:
        captured: dict[str, object] = {}

        @asynccontextmanager
        async def transport(endpoint, *, http_client):
            captured["endpoint"] = endpoint
            captured["headers"] = dict(http_client.headers)
            yield object(), object(), None

        class Session:
            def __init__(self, *_args): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *_args): return None
            async def initialize(self): return None
            async def call_tool(self, name, arguments):
                captured["tool"] = name
                captured["arguments"] = arguments
                return SimpleNamespace(
                    isError=False,
                    content=[SimpleNamespace(type="text", text='{"rows":[]}')],
                )

        provider = {
            "protocol": "mcp",
            "connector_type": "postgresql_mcp",
            "auth_type": "execution_capability",
            "connection_config": {},
            "endpoint": "http://postgres-mcp:8091/mcp",
            "network_zone": "internal",
            "timeout_policy": {"read_seconds": 5, "connect_seconds": 2},
            "request_mapping": {},
            "path_or_tool": "db_select",
            "revision_id": "revision-1",
        }
        with (
            patch.object(capability_gateway, "streamable_http_client", transport),
            patch.object(capability_gateway, "ClientSession", Session),
            patch.object(capability_gateway, "_validate_network", AsyncMock()),
        ):
            result = await capability_gateway._invoke_provider(
                provider,
                {"sql": "SELECT 1", "resource_scope": {"database": "hidden"}},
                None,
                "cap1.secret-token",
                execution_id="execution-1",
                binding_id="binding-1",
                scope_revision_id="scope-1",
                idempotency="SAFE_RETRY",
            )
        headers = {str(key).lower(): str(value) for key, value in captured["headers"].items()}
        self.assertEqual(headers["authorization"], "Bearer cap1.secret-token")
        self.assertEqual(headers["x-hermes-execution-id"], "execution-1")
        self.assertEqual(headers["x-hermes-binding-id"], "binding-1")
        self.assertEqual(captured["arguments"], {"sql": "SELECT 1"})
        self.assertNotIn("access_token", captured["arguments"])
        self.assertEqual(result, {"rows": []})


if __name__ == "__main__":
    unittest.main()
