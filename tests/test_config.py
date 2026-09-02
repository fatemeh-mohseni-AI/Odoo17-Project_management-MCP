from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from odoo_project_mcp.config import Settings
from odoo_project_mcp.errors import ConfigurationError
from odoo_project_mcp.policy import AccessPolicy

BASE_ENV = {
    "ODOO_URL": "https://odoo.example.test",
    "ODOO_DB": "company",
    "ODOO_USERNAME": "ai-service@example.test",
    "ODOO_API_KEY": "not-a-real-secret",
    "MCP_AUTH_TOKEN": "test-token-that-is-at-least-32-characters-long",
}


class SettingsTests(unittest.TestCase):
    def test_empty_allowlist_fails_closed(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings.from_env(BASE_ENV)

    def test_explicit_project_creation_allows_bootstrap(self) -> None:
        settings = Settings.from_env({**BASE_ENV, "ODOO_ALLOW_PROJECT_CREATION": "true"})
        self.assertEqual(settings.allowed_project_ids, frozenset())
        self.assertTrue(settings.allow_project_creation)

    def test_ids_and_api_key_are_parsed(self) -> None:
        settings = Settings.from_env(
            {
                **BASE_ENV,
                "ODOO_ALLOWED_PROJECT_IDS": "7, 9,7",
                "ODOO_ALLOWED_ASSIGNEE_USER_IDS": "2,3",
            }
        )
        self.assertEqual(settings.allowed_project_ids, frozenset({7, 9}))
        self.assertEqual(settings.allowed_assignee_user_ids, frozenset({2, 3}))

    def test_url_cannot_embed_credentials(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings.from_env(
                {
                    **BASE_ENV,
                    "ODOO_URL": "https://user:pass@example.test",
                    "ODOO_ALLOWED_PROJECT_IDS": "1",
                }
            )

    def test_streamable_http_is_the_authenticated_default(self) -> None:
        settings = Settings.from_env({**BASE_ENV, "ODOO_ALLOWED_PROJECT_IDS": "1"})
        self.assertEqual(settings.mcp_transport, "streamable-http")
        self.assertEqual(settings.mcp_host, "0.0.0.0")
        self.assertEqual(settings.mcp_port, 31080)

    def test_streamable_http_requires_a_strong_token(self) -> None:
        environment = {**BASE_ENV, "ODOO_ALLOWED_PROJECT_IDS": "1"}
        environment.pop("MCP_AUTH_TOKEN")
        with self.assertRaises(ConfigurationError):
            Settings.from_env(environment)
        with self.assertRaises(ConfigurationError):
            Settings.from_env({**environment, "MCP_AUTH_TOKEN": "too-short"})

    def test_stdio_remains_available_without_an_http_token(self) -> None:
        environment = {**BASE_ENV, "ODOO_ALLOWED_PROJECT_IDS": "1", "MCP_TRANSPORT": "stdio"}
        environment.pop("MCP_AUTH_TOKEN")
        settings = Settings.from_env(environment)
        self.assertEqual(settings.mcp_transport, "stdio")
        self.assertIsNone(settings.mcp_auth_token)

    def test_transport_and_port_are_validated(self) -> None:
        with self.assertRaises(ConfigurationError):
            Settings.from_env({**BASE_ENV, "ODOO_ALLOWED_PROJECT_IDS": "1", "MCP_TRANSPORT": "sse"})
        with self.assertRaises(ConfigurationError):
            Settings.from_env({**BASE_ENV, "ODOO_ALLOWED_PROJECT_IDS": "1", "MCP_PORT": "70000"})


class PolicyTests(unittest.TestCase):
    def test_created_project_is_persisted_and_reloaded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "state.json"
            settings = Settings(
                odoo_url="https://odoo.example.test",
                database="db",
                username="service",
                secret="secret",
                allowed_project_ids=frozenset({1}),
                allowed_assignee_user_ids=frozenset(),
                allow_project_creation=True,
                state_file=state_file,
            )
            policy = AccessPolicy(settings)
            self.assertTrue(policy.remember_created_project(5))
            self.assertEqual(AccessPolicy(settings).allowed_project_ids, frozenset({1, 5}))
            self.assertEqual(state_file.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
