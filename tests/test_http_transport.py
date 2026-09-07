from __future__ import annotations

import asyncio
import unittest

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from odoo_project_mcp.config import Settings
from odoo_project_mcp.http_transport import create_http_app
from odoo_project_mcp.server import mcp

TOKEN = "http-test-token-that-is-more-than-32-characters"


def _settings() -> Settings:
    return Settings(
        odoo_url="https://odoo.example.test",
        database="test",
        username="service",
        secret="odoo-secret",
        allowed_project_ids=frozenset({1}),
        allowed_assignee_user_ids=frozenset(),
        mcp_auth_token=TOKEN,
    )


class HttpTransportTests(unittest.TestCase):
    def test_health_and_authentication_contract(self) -> None:
        async def inspect() -> None:
            gateway = create_http_app(mcp, _settings())
            transport = httpx2.ASGITransport(app=gateway)
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                health = await client.get("/health")
                self.assertEqual(health.status_code, 200)
                self.assertEqual(
                    health.json(),
                    {"status": "ok", "transport": "streamable-http", "version": "0.2.1"},
                )

                missing = await client.post("/mcp")
                self.assertEqual(missing.status_code, 401)
                self.assertEqual(missing.json()["error"], "authorization_required")

                invalid = await client.post(
                    "/mcp", headers={"Authorization": "Bearer invalid-token"}
                )
                self.assertEqual(invalid.status_code, 403)
                self.assertEqual(invalid.json()["error"], "invalid_token")

        asyncio.run(inspect())

    def test_valid_token_allows_real_mcp_communication(self) -> None:
        async def inspect() -> None:
            gateway = create_http_app(mcp, _settings())
            transport = httpx2.ASGITransport(app=gateway)
            async with (
                gateway.application.router.lifespan_context(gateway.application),
                httpx2.AsyncClient(
                    transport=transport,
                    base_url="http://testserver",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                ) as http_client,
            ):
                remote_transport = streamable_http_client(
                    "http://testserver/mcp", http_client=http_client
                )
                async with Client(remote_transport, mode="legacy") as client:
                    page = await client.list_tools()
                    self.assertEqual(len(page.tools), 32)
                    self.assertIn("create_task", {tool.name for tool in page.tools})

        asyncio.run(inspect())


if __name__ == "__main__":
    unittest.main()
