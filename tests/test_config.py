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
