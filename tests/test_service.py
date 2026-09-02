from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any, ClassVar

from odoo_project_mcp.config import Settings
from odoo_project_mcp.errors import AccessDeniedError, ValidationError
from odoo_project_mcp.policy import AccessPolicy
from odoo_project_mcp.service import PROJECT_FIELDS, TASK_FIELDS, ProjectService


def _project(project_id: int, name: str) -> dict[str, Any]:
    return {
        **{field: False for field in PROJECT_FIELDS},
        "id": project_id,
        "name": name,
        "active": True,
        "allow_milestones": True,
    }


def _task(task_id: int, project_id: int, name: str) -> dict[str, Any]:
    return {
        **{field: False for field in TASK_FIELDS},
        "id": task_id,
        "name": name,
        "active": True,
        "project_id": [project_id, f"Project {project_id}"],
        "stage_id": [100, "Backlog"],
        "state": "01_in_progress",
        "user_ids": [],
        "tag_ids": [],
        "allocated_hours": 0.0,
        "child_ids": [],
        "depend_on_ids": [],
        "dependent_ids": [],
    }


class FakeClient:
    uid = 7
    version: ClassVar[dict[str, Any]] = {
        "server_version": "17.0",
        "server_version_info": [17, 0, 0],
    }

    def __init__(self) -> None:
        self.records: dict[str, dict[int, dict[str, Any]]] = {
            "project.project": {1: _project(1, "Allowed"), 2: _project(2, "Denied")},
            "project.task": {10: _task(10, 1, "Allowed task"), 20: _task(20, 2, "Denied task")},
            "project.task.type": {
                100: {
                    "id": 100,
                    "name": "Backlog",
                    "sequence": 1,
                    "fold": False,
                    "description": False,
                    "project_ids": [1],
                },
                101: {
                    "id": 101,
                    "name": "Global",
                    "sequence": 2,
                    "fold": False,
                    "description": False,
                    "project_ids": [],
                },
                200: {
                    "id": 200,
                    "name": "Secret",
                    "sequence": 1,
                    "fold": False,
                    "description": False,
                    "project_ids": [2],
                },
            },
            "project.tags": {
                300: {"id": 300, "name": "Feature", "color": 2, "project_ids": [1]},
                400: {"id": 400, "name": "Secret", "color": 3, "project_ids": [2]},
            },
            "project.milestone": {},
            "account.analytic.line": {
                500: {
                    "id": 500,
                    "name": "Work",
                    "date": "2026-09-01",
                    "unit_amount": 2.0,
                    "project_id": [1, "Allowed"],
                    "task_id": [10, "Allowed task"],
                    "user_id": [8, "Dev"],
                },
                600: {
                    "id": 600,
                    "name": "Secret",
                    "date": "2026-09-01",
                    "unit_amount": 1.0,
                    "project_id": [2, "Denied"],
                    "task_id": [20, "Denied task"],
                    "user_id": [8, "Dev"],
                },
            },
            "res.users": {
                8: {
                    "id": 8,
                    "name": "Developer",
                    "login": "dev@example.test",
                    "active": True,
                    "share": False,
                    "partner_id": [80, "Developer"],
                },
                9: {
                    "id": 9,
                    "name": "Portal",
                    "login": "portal@example.test",
                    "active": True,
                    "share": True,
                    "partner_id": [90, "Portal"],
                },
            },
        }
        self.writes: list[tuple[str, list[int], dict[str, Any]]] = []
        self.unlinks: list[tuple[str, list[int]]] = []
        self.last_search: tuple[str, list[Any]] | None = None
        self.next_ids = {
            "project.project": 3,
            "project.task": 11,
            "project.task.type": 102,
            "project.tags": 301,
            "project.milestone": 701,
            "account.analytic.line": 501,
        }

    def read(self, model: str, ids: list[int], fields: list[str]) -> list[dict[str, Any]]:
        return [
            deepcopy(self.records[model][record_id])
            for record_id in ids
            if record_id in self.records[model]
        ]

    def search_read(
        self,
        model: str,
        domain: list[Any],
        fields: list[str],
        *,
        limit: int = 100,
        offset: int = 0,
        order: str = "id asc",
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self.last_search = (model, deepcopy(domain))
        records = list(self.records[model].values())
        # Enough domain behavior for the policy and creation tests.
        for condition in domain:
            if not isinstance(condition, list) or len(condition) != 3:
                continue
            field, operator, expected = condition
            if operator == "in" and field == "id":
                records = [row for row in records if row["id"] in expected]
            elif operator == "=" and field in {"active", "share", "project_id"}:
                records = [
                    row
                    for row in records
                    if (
                        row.get(field, False)[0]
                        if isinstance(row.get(field), list)
                        else row.get(field)
                    )
                    == expected
                ]
        return [
            deepcopy({key: row.get(key, False) for key in fields})
            for row in records[offset : offset + limit]
        ]

    def create(self, model: str, values: dict[str, Any]) -> int:
        record_id = self.next_ids[model]
        self.next_ids[model] += 1
        if model == "project.project":
            record = _project(record_id, values["name"])
        elif model == "project.task":
            record = _task(record_id, values["project_id"], values["name"])
            record.update(
                {
                    key: value
                    for key, value in values.items()
                    if key not in {"user_ids", "tag_ids", "depend_on_ids"}
                }
            )
            for field in ("user_ids", "tag_ids", "depend_on_ids"):
                if field in values:
                    record[field] = values[field][0][2]
        elif model == "project.task.type" or model == "project.tags":
            record = {"id": record_id, **values, "project_ids": values["project_ids"][0][2]}
        elif model == "project.milestone":
            record = {
                **{
                    field: False
                    for field in (
                        "name",
                        "project_id",
                        "deadline",
                        "is_reached",
                        "reached_date",
                        "task_count",
                        "done_task_count",
                    )
                },
                "id": record_id,
                **values,
            }
            record["project_id"] = [values["project_id"], "Allowed"]
        else:
            record = {"id": record_id, **values, "user_id": [values.get("user_id", 7), "User"]}
            record["project_id"] = [values["project_id"], "Allowed"]
            record["task_id"] = [values["task_id"], "Task"]
        self.records[model][record_id] = record
        return record_id

    def write(self, model: str, ids: list[int], values: dict[str, Any]) -> bool:
        self.writes.append((model, ids, deepcopy(values)))
        for record_id in ids:
            for key, value in values.items():
                if (
                    isinstance(value, list)
                    and value
                    and isinstance(value[0], list)
                    and value[0][:2] == [6, 0]
                ):
                    value = value[0][2]
                self.records[model][record_id][key] = value
        return True

    def unlink(self, model: str, ids: list[int]) -> bool:
        self.unlinks.append((model, ids))
        for record_id in ids:
            self.records[model].pop(record_id, None)
        return True

    def fields_get(self, model: str, fields: list[str]) -> dict[str, dict[str, Any]]:
        if model == "project.project":
            return {
                "privacy_visibility": {
                    "selection": [
                        ["followers", "Invited"],
                        ["employees", "All internal"],
                        ["portal", "Portal"],
                    ]
                }
            }
        if model == "project.task":
            return {"state": {"selection": [["01_in_progress", "In Progress"], ["1_done", "Done"]]}}
        if model == "account.analytic.line":
            return {field: {"type": "char"} for field in fields}
        return {field: {} for field in fields}

    def check_access(self, model: str, operation: str) -> bool:
        return True

    def execute(self, model: str, method: str, args: list[Any], kwargs: dict[str, Any]) -> int:
        self.assert_message_post(model, method, args)
        return 999

    @staticmethod
    def assert_message_post(model: str, method: str, args: list[Any]) -> None:
        assert model == "project.task" and method == "message_post" and args


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(
            odoo_url="https://odoo.example.test",
            database="db",
            username="service",
            secret="secret",
            allowed_project_ids=frozenset({1}),
            allowed_assignee_user_ids=frozenset({8}),
            allow_project_creation=True,
            enable_hard_delete=True,
            state_file=Path(self.temp.name) / "state.json",
        )
        self.client = FakeClient()
        self.service = ProjectService(self.client, AccessPolicy(self.settings), self.settings)  # type: ignore[arg-type]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_denied_project_is_not_returned(self) -> None:
        with self.assertRaises(AccessDeniedError):
            self.service.get_project(2)

    def test_task_project_is_resolved_before_access(self) -> None:
        with self.assertRaises(AccessDeniedError):
            self.service.get_task(20)

    def test_create_task_validates_related_records_and_builds_odoo_commands(self) -> None:
        task = self.service.create_task(
            1,
            "Implement API",
            assignee_user_ids=[8],
            tag_ids=[300],
            stage_id=100,
            allocated_hours=5.5,
        )
        self.assertEqual(task["project_id"], 1)
        self.assertEqual(task["user_ids"], [8])
        self.assertEqual(task["tag_ids"], [300])

    def test_create_task_rejects_stage_from_other_project(self) -> None:
        with self.assertRaises(AccessDeniedError):
            self.service.create_task(1, "Nope", stage_id=200)

    def test_create_task_rejects_portal_or_unapproved_user(self) -> None:
        with self.assertRaises(AccessDeniedError):
            self.service.create_task(1, "Nope", assignee_user_ids=[9])

    def test_global_stage_can_be_used_but_not_edited(self) -> None:
        moved = self.service.move_task(10, 101)
        self.assertEqual(moved["stage_id"], 101)
        with self.assertRaises(AccessDeniedError):
            self.service.update_stage(1, 101, {"name": "Changed globally"})

    def test_delete_requires_exact_confirmation(self) -> None:
        with self.assertRaises(ValidationError):
            self.service.delete_task(10, "yes")
        result = self.service.delete_task(10, "DELETE TASK 10")
        self.assertTrue(result["deleted"])

    def test_create_project_is_added_to_runtime_policy(self) -> None:
        created = self.service.create_project("New Project")
        self.assertEqual(created["id"], 3)
        self.assertIn(3, self.service.policy.allowed_project_ids)

    def test_timesheet_access_is_project_scoped(self) -> None:
        with self.assertRaises(AccessDeniedError):
            self.service.update_timesheet(600, {"unit_amount": 2.0})

    def test_task_state_is_validated_from_live_metadata(self) -> None:
        with self.assertRaises(ValidationError):
            self.service.set_task_state(10, "invented")
        task = self.service.set_task_state(10, "1_done")
        self.assertEqual(task["state"], "1_done")

    def test_list_tasks_always_contains_project_allowlist_domain(self) -> None:
        self.service.list_tasks(limit=10)
        assert self.client.last_search is not None
        self.assertIn(["project_id", "in", [1]], self.client.last_search[1])


if __name__ == "__main__":
    unittest.main()
