from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("MCP_GATEWAY_SIGNING_KEY", "test-signing-key-that-is-at-least-32-chars")

from hermes_mcp_gateway import capability_gateway, server


class JsonObjectTests(unittest.TestCase):
    def test_normalizes_asyncpg_json_text(self) -> None:
        self.assertEqual(capability_gateway._json_object('{"quota_policy":{"calls_per_minute":5}}'), {
            "quota_policy": {"calls_per_minute": 5}
        })
        self.assertEqual(capability_gateway._json_object({"ready": True}), {"ready": True})
        self.assertEqual(capability_gateway._json_object("[]"), {})
        self.assertEqual(capability_gateway._json_object("not-json"), {})


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


if __name__ == "__main__":
    unittest.main()
