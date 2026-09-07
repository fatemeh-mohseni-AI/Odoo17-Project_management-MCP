"""Policy-enforced Project application operations exposed by the MCP layer."""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any

from .config import Settings
from .errors import (
    AccessDeniedError,
    CapabilityUnavailableError,
    OdooRPCError,
    ValidationError,
)
from .odoo import OdooClient
from .policy import AccessPolicy

logger = logging.getLogger(__name__)

PROJECT_FIELDS = [
    "id",
    "name",
    "description",
    "active",
    "date_start",
    "date",
    "privacy_visibility",
    "allow_task_dependencies",
    "allow_milestones",
    "label_tasks",
    "open_task_count",
    "closed_task_count",
    "milestone_count",
]
TASK_FIELDS = [
    "id",
    "name",
    "description",
    "active",
    "project_id",
    "stage_id",
    "state",
    "user_ids",
    "tag_ids",
    "allocated_hours",
    "date_deadline",
    "date_assign",
    "date_last_stage_update",
    "date_end",
    "priority",
    "parent_id",
    "child_ids",
    "depend_on_ids",
    "dependent_ids",
    "milestone_id",
    "subtask_count",
    "create_date",
    "write_date",
]
# Deliberately small: list/search tools are used for planning context and must not
# return large descriptions, dependency arrays, or audit timestamps for every task.
# Call get_task when full details are needed for one selected record.
TASK_LIST_FIELDS = [
    "id",
    "name",
    "active",
    "project_id",
    "stage_id",
    "state",
    "user_ids",
    "tag_ids",
    "allocated_hours",
    "date_deadline",
    "priority",
    "parent_id",
    "subtask_count",
    "milestone_id",
]
STAGE_FIELDS = ["id", "name", "sequence", "fold", "description", "project_ids"]
TAG_FIELDS = ["id", "name", "color", "project_ids"]
MILESTONE_FIELDS = [
    "id",
    "name",
    "project_id",
    "deadline",
    "is_reached",
    "reached_date",
    "task_count",
    "done_task_count",
]


def _m2o_id(value: Any) -> int | None:
    if value in (None, False):
        return None
    if isinstance(value, (list, tuple)) and value:
        return int(value[0])
    return int(value)


def _positive_id(value: int, name: str) -> int:
    if isinstance(value, bool) or int(value) <= 0:
        raise ValidationError(f"{name} must be a positive integer")
    return int(value)


def _bounded_limit(value: int, maximum: int = 200) -> int:
    if not 1 <= value <= maximum:
        raise ValidationError(f"limit must be between 1 and {maximum}")
    return value


def _finite_hours(value: float, name: str, *, allow_zero: bool) -> float:
    converted = float(value)
    if not math.isfinite(converted) or converted < 0 or (not allow_zero and converted == 0):
        qualifier = "non-negative" if allow_zero else "greater than zero"
        raise ValidationError(f"{name} must be a finite number {qualifier}")
    return converted


def _date_value(value: str | None, name: str) -> str | bool:
    if value is None:
        return False
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValidationError(f"{name} must use YYYY-MM-DD") from exc


def _datetime_value(value: str | None, name: str) -> str | bool:
    if value is None:
        return False
    raw = value.strip()
    try:
        if len(raw) == 10:
            parsed = datetime.combine(date.fromisoformat(raw), datetime.max.time()).replace(
                microsecond=0
            )
        else:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(UTC).replace(tzinfo=None)
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise ValidationError(
            f"{name} must be YYYY-MM-DD or an ISO-8601 date-time; timezone values are stored in UTC"
        ) from exc


class ProjectService:
    """Narrow service API. No caller can select an arbitrary Odoo model or method."""

    def __init__(self, client: OdooClient, policy: AccessPolicy, settings: Settings):
        self.client = client
        self.policy = policy
        self.settings = settings
        self._selection_cache: dict[tuple[str, str], dict[str, str]] = {}
        self._readable_fields_cache: dict[tuple[str, tuple[str, ...]], tuple[str, ...]] = {}
        self._timesheet_fields_cache: frozenset[str] | None = None

    # Connection and identity -------------------------------------------------

    def health(self) -> dict[str, Any]:
        version = self.client.version
        permissions = {
            model: {
                operation: self.client.check_access(model, operation)
                for operation in ("read", "create", "write", "unlink")
            }
            for model in ("project.project", "project.task", "project.task.type", "project.tags")
        }
        try:
            self._timesheet_fields()
            timesheets = True
        except CapabilityUnavailableError:
            timesheets = False
        return {
            "ok": True,
            "odoo_version": version.get("server_version"),
            "authenticated_uid": self.client.uid,
            "allowed_project_ids": sorted(self.policy.allowed_project_ids),
            "project_creation_enabled": self.settings.allow_project_creation,
            "hard_delete_enabled": self.settings.enable_hard_delete,
            "timesheets_available": timesheets,
            "permissions": permissions,
        }

    def list_assignable_users(
        self, query: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        domain: list[Any] = [["active", "=", True], ["share", "=", False]]
        if self.settings.allowed_assignee_user_ids:
            domain.append(["id", "in", sorted(self.settings.allowed_assignee_user_ids)])
        if query:
            domain.extend(["|", ["name", "ilike", query], ["login", "ilike", query]])
        return self.client.search_read(
            "res.users",
            domain,
            ["id", "name", "login", "partner_id"],
            limit=_bounded_limit(limit),
            order="name asc, id asc",
        )

    # Projects ---------------------------------------------------------------

    def list_projects(self) -> list[dict[str, Any]]:
        ids = sorted(self.policy.allowed_project_ids)
        if not ids:
            return []
        return self.client.search_read(
            "project.project",
            [["id", "in", ids]],
            self._readable_fields("project.project", PROJECT_FIELDS),
            limit=max(len(ids), 1),
            order="name asc, id asc",
        )

    def get_project(self, project_id: int) -> dict[str, Any]:
        return self._project(project_id)

    def create_project(
        self,
        name: str,
        *,
        description: str | None = None,
        date_start: str | None = None,
        date_end: str | None = None,
        privacy_visibility: str = "followers",
        allow_task_dependencies: bool = True,
        allow_milestones: bool = True,
        task_label: str = "Tasks",
    ) -> dict[str, Any]:
        if not self.settings.allow_project_creation:
            raise AccessDeniedError("Project creation is disabled by ODOO_ALLOW_PROJECT_CREATION")
        self._require_text(name, "name", 255)
        self._require_text(task_label, "task_label", 255)
        if description is not None:
            self._require_text(description, "description", 100_000)
        self._validate_selection("project.project", "privacy_visibility", privacy_visibility)
        values: dict[str, Any] = {
            "name": name.strip(),
            "description": description or False,
            "privacy_visibility": privacy_visibility,
            "allow_task_dependencies": allow_task_dependencies,
            "allow_milestones": allow_milestones,
            "label_tasks": task_label.strip() or "Tasks",
        }
        if date_start is not None:
            values["date_start"] = _date_value(date_start, "date_start")
        if date_end is not None:
            values["date"] = _date_value(date_end, "date_end")
        project_id = self.client.create("project.project", values)
        persisted = self.policy.remember_created_project(project_id)
        self._audit("create", "project.project", [project_id], project_id)
        result = self._project(project_id)
        if self.settings.persist_created_projects and not persisted:
            result["policy_warning"] = (
                "Project was created and is allowed for this process, but the state file could not be "
                "persisted. Add the ID to ODOO_ALLOWED_PROJECT_IDS before restart."
            )
        return result

    def update_project(self, project_id: int, changes: dict[str, Any]) -> dict[str, Any]:
        self._project(project_id)
        allowed = {
            "name",
            "description",
            "date_start",
            "date",
            "privacy_visibility",
            "allow_task_dependencies",
            "allow_milestones",
            "label_tasks",
        }
        self._reject_unknown(changes, allowed)
        values = dict(changes)
        if "name" in values:
            self._require_text(values["name"], "name", 255)
            values["name"] = values["name"].strip()
        if "description" in values:
            if values["description"] is None:
                values["description"] = False
            else:
                self._require_text(values["description"], "description", 100_000)
        if "label_tasks" in values:
            self._require_text(values["label_tasks"], "task_label", 255)
            values["label_tasks"] = values["label_tasks"].strip()
        if "privacy_visibility" in values:
            self._validate_selection(
                "project.project", "privacy_visibility", values["privacy_visibility"]
            )
        for field in ("date_start", "date"):
            if field in values:
                values[field] = _date_value(values[field], field)
        if not values:
            raise ValidationError("No project changes were supplied")
        self.client.write("project.project", [project_id], values)
        self._audit("update", "project.project", [project_id], project_id, values.keys())
        return self._project(project_id)

    # Stages / board ---------------------------------------------------------

    def list_stages(self, project_id: int) -> list[dict[str, Any]]:
        self._project(project_id)
        domain = ["|", ["project_ids", "=", False], ["project_ids", "in", [project_id]]]
        return self.client.search_read(
            "project.task.type",
            domain,
            self._readable_fields("project.task.type", STAGE_FIELDS),
            limit=200,
            order="sequence asc, id asc",
        )

    def create_stage(
        self,
        project_id: int,
        name: str,
        *,
        sequence: int = 10,
        fold: bool = False,
        description: str | None = None,
    ) -> dict[str, Any]:
        self._project(project_id)
        self._require_text(name, "name", 255)
        if description is not None:
            self._require_text(description, "description", 10_000)
        if not 0 <= sequence <= 1_000_000:
            raise ValidationError("sequence must be between 0 and 1000000")
        stage_id = self.client.create(
            "project.task.type",
            {
                "name": name.strip(),
                "sequence": sequence,
                "fold": fold,
                "description": description or False,
                "project_ids": [[6, 0, [project_id]]],
            },
        )
        self._audit("create", "project.task.type", [stage_id], project_id)
        return self._stage(stage_id, project_id)

    def update_stage(
        self, project_id: int, stage_id: int, changes: dict[str, Any]
    ) -> dict[str, Any]:
        stage = self._stage(stage_id, project_id, require_exclusively_allowed=True)
        self._reject_unknown(changes, {"name", "sequence", "fold", "description"})
        values = dict(changes)
        if "name" in values:
            self._require_text(values["name"], "name", 255)
            values["name"] = values["name"].strip()
        if "description" in values:
            if values["description"] is None:
                values["description"] = False
            else:
                self._require_text(values["description"], "description", 10_000)
        if "sequence" in values and not 0 <= int(values["sequence"]) <= 1_000_000:
            raise ValidationError("sequence must be between 0 and 1000000")
        if not values:
            raise ValidationError("No stage changes were supplied")
        self.client.write("project.task.type", [stage["id"]], values)
        self._audit("update", "project.task.type", [stage_id], project_id, values.keys())
        return self._stage(stage_id, project_id)

    def get_project_board(
        self, project_id: int, *, include_archived: bool = False, limit: int = 50
    ) -> dict[str, Any]:
        project = self._project(project_id)
        stages = self.list_stages(project_id)
        tasks = self.list_tasks(
            project_id=project_id,
            include_archived=include_archived,
            limit=_bounded_limit(limit, 100),
        )
        grouped: dict[int | None, list[dict[str, Any]]] = {stage["id"]: [] for stage in stages}
        grouped[None] = []
        for task in tasks:
            grouped.setdefault(_m2o_id(task.get("stage_id")), []).append(task)
        return {
            "project": project,
            "columns": [dict(stage, tasks=grouped.pop(stage["id"], [])) for stage in stages],
            "unmapped_tasks": [task for values in grouped.values() for task in values],
            "returned_task_count": len(tasks),
            "possibly_truncated": len(tasks) == limit,
        }

    # Tasks ------------------------------------------------------------------

    def list_tasks(
        self,
        *,
        project_id: int | None = None,
        query: str | None = None,
        stage_id: int | None = None,
        stage_name: str | None = None,
        assignee_user_id: int | None = None,
        tag_id: int | None = None,
        parent_task_id: int | None = None,
        deadline_before: str | None = None,
        include_archived: bool = False,
        limit: int = 25,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        allowed = sorted(self.policy.allowed_project_ids)
        if not allowed:
            return []
        domain: list[Any] = [["project_id", "in", allowed]]
        if project_id is not None:
            self._project(project_id)
            domain.append(["project_id", "=", project_id])
        if query:
            domain.append(["name", "ilike", query])
        if stage_id is not None and stage_name is not None:
            raise ValidationError("stage_id and stage_name are mutually exclusive")
        if stage_name is not None:
            if project_id is None:
                raise ValidationError("project_id is required when filtering by stage_name")
            self._require_text(stage_name, "stage_name", 255)
            matches = self.client.search_read(
                "project.task.type",
                [
                    "&",
                    ["name", "=ilike", stage_name.strip()],
                    "|",
                    ["project_ids", "=", False],
                    ["project_ids", "in", [project_id]],
                ],
                ["id", "name"],
                limit=3,
                order="sequence asc, id asc",
            )
            if not matches:
                raise ValidationError(
                    f"No stage named {stage_name.strip()!r} is available in project {project_id}"
                )
            if len(matches) > 1:
                raise ValidationError(
                    f"Multiple stages are named {stage_name.strip()!r}; use stage_id instead"
                )
            stage_id = int(matches[0]["id"])
        if stage_id is not None:
            if project_id is None:
                raise ValidationError("project_id is required when filtering by stage_id")
            self._stage(stage_id, project_id)
            domain.append(["stage_id", "=", stage_id])
        if assignee_user_id is not None:
            assignee_user_id = _positive_id(assignee_user_id, "assignee_user_id")
            self.policy.require_assignees([assignee_user_id])
            domain.append(["user_ids", "in", [assignee_user_id]])
        if tag_id is not None:
            if project_id is None:
                raise ValidationError("project_id is required when filtering by tag_id")
            self._tag(tag_id, project_id)
            domain.append(["tag_ids", "in", [tag_id]])
        if parent_task_id is not None:
            parent = self._task(parent_task_id)
            if project_id is not None and _m2o_id(parent["project_id"]) != project_id:
                raise ValidationError("parent_task_id is not in project_id")
            domain.append(["parent_id", "=", parent_task_id])
        if deadline_before is not None:
            domain.append(
                ["date_deadline", "<=", _datetime_value(deadline_before, "deadline_before")]
            )
        if include_archived:
            domain.append(["active", "in", [True, False]])
        elif not include_archived:
            domain.append(["active", "=", True])
        if offset < 0:
            raise ValidationError("offset cannot be negative")
        return self.client.search_read(
            "project.task",
            domain,
            self._readable_fields("project.task", TASK_LIST_FIELDS),
            limit=_bounded_limit(limit, 100),
            offset=offset,
            order="priority desc, sequence asc, id asc",
            context={"active_test": not include_archived},
        )

    def get_task(self, task_id: int) -> dict[str, Any]:
        return self._task(task_id)

    def create_task(
        self,
        project_id: int,
        name: str,
        *,
        description: str | None = None,
        assignee_user_ids: Iterable[int] = (),
        allocated_hours: float | None = None,
        stage_id: int | None = None,
        tag_ids: Iterable[int] = (),
        deadline: str | None = None,
        parent_task_id: int | None = None,
        priority: str = "0",
        blocked_by_task_ids: Iterable[int] = (),
        milestone_id: int | None = None,
    ) -> dict[str, Any]:
        self._project(project_id)
        self._require_text(name, "name", 500)
        if description is not None:
            self._require_text(description, "description", 100_000)
        users = self._validate_users(assignee_user_ids)
        tags = self._validate_tags(tag_ids, project_id)
        blockers = self._validate_tasks_in_project(blocked_by_task_ids, project_id)
        if stage_id is not None:
            self._stage(stage_id, project_id)
        if parent_task_id is not None:
            parent = self._task(parent_task_id)
            if _m2o_id(parent["project_id"]) != project_id:
                raise ValidationError("A subtask must use the same project as its parent")
        if milestone_id is not None:
            self._milestone(milestone_id, project_id)
        if priority not in {"0", "1"}:
            raise ValidationError("priority must be '0' (normal) or '1' (high)")
        values: dict[str, Any] = {
            "project_id": project_id,
            "name": name.strip(),
            "description": description or False,
            "user_ids": [[6, 0, users]],
            "tag_ids": [[6, 0, tags]],
            "priority": priority,
        }
        if allocated_hours is not None:
            values["allocated_hours"] = _finite_hours(
                allocated_hours, "allocated_hours", allow_zero=True
            )
        if stage_id is not None:
            values["stage_id"] = stage_id
        if deadline is not None:
            values["date_deadline"] = _datetime_value(deadline, "deadline")
        if parent_task_id is not None:
            values["parent_id"] = parent_task_id
        if blockers:
            values["depend_on_ids"] = [[6, 0, blockers]]
        if milestone_id is not None:
            values["milestone_id"] = milestone_id
        task_id = self.client.create("project.task", values)
        self._audit("create", "project.task", [task_id], project_id)
        return self._task(task_id)

    def update_task(self, task_id: int, changes: dict[str, Any]) -> dict[str, Any]:
        task = self._task(task_id)
        project_id = _m2o_id(task["project_id"])
        assert project_id is not None
        allowed = {
            "name",
            "description",
            "user_ids",
            "allocated_hours",
            "stage_id",
            "tag_ids",
            "date_deadline",
            "parent_id",
            "priority",
            "depend_on_ids",
            "milestone_id",
        }
        self._reject_unknown(changes, allowed)
        values = dict(changes)
        if "name" in values:
            self._require_text(values["name"], "name", 500)
            values["name"] = values["name"].strip()
        if "description" in values:
            if values["description"] is None:
                values["description"] = False
            else:
                self._require_text(values["description"], "description", 100_000)
        if "user_ids" in values:
            values["user_ids"] = [[6, 0, self._validate_users(values["user_ids"])]]
        if "tag_ids" in values:
            values["tag_ids"] = [[6, 0, self._validate_tags(values["tag_ids"], project_id)]]
        if "depend_on_ids" in values:
            dependencies = self._validate_tasks_in_project(values["depend_on_ids"], project_id)
            if task_id in dependencies:
                raise ValidationError("A task cannot block itself")
            values["depend_on_ids"] = [[6, 0, dependencies]]
        if "stage_id" in values:
            self._stage(int(values["stage_id"]), project_id)
        if "allocated_hours" in values:
            values["allocated_hours"] = _finite_hours(
                values["allocated_hours"], "allocated_hours", allow_zero=True
            )
        if "date_deadline" in values:
            values["date_deadline"] = _datetime_value(values["date_deadline"], "date_deadline")
        if "parent_id" in values:
            parent_id = values["parent_id"]
            if parent_id in (None, False):
                values["parent_id"] = False
            else:
                parent = self._task(int(parent_id))
                if int(parent_id) == task_id:
                    raise ValidationError("A task cannot be its own parent")
                if _m2o_id(parent["project_id"]) != project_id:
                    raise ValidationError("A subtask must use the same project as its parent")
        if "priority" in values and values["priority"] not in {"0", "1"}:
            raise ValidationError("priority must be '0' or '1'")
        if "milestone_id" in values:
            if values["milestone_id"] in (None, False):
                values["milestone_id"] = False
            else:
                self._milestone(int(values["milestone_id"]), project_id)
        if not values:
            raise ValidationError("No task changes were supplied")
        self.client.write("project.task", [task_id], values)
        self._audit("update", "project.task", [task_id], project_id, values.keys())
        return self._task(task_id)

    def move_task(self, task_id: int, stage_id: int) -> dict[str, Any]:
        return self.update_task(task_id, {"stage_id": stage_id})

    def list_task_states(self) -> list[dict[str, str]]:
        return [
            {"value": key, "label": label}
            for key, label in self._selection("project.task", "state").items()
        ]

    def set_task_state(self, task_id: int, state: str) -> dict[str, Any]:
        task = self._task(task_id)
        project_id = _m2o_id(task["project_id"])
        assert project_id is not None
        self._validate_selection("project.task", "state", state)
        self.client.write("project.task", [task_id], {"state": state})
        self._audit("state", "project.task", [task_id], project_id, ["state"])
        return self._task(task_id)

    def archive_task(self, task_id: int, archived: bool = True) -> dict[str, Any]:
        task = self._task(task_id)
        project_id = _m2o_id(task["project_id"])
        assert project_id is not None
        self.client.write("project.task", [task_id], {"active": not archived})
        self._audit("archive" if archived else "unarchive", "project.task", [task_id], project_id)
        return self._task(task_id)

    def delete_task(self, task_id: int, confirmation: str) -> dict[str, Any]:
        task = self._task(task_id)
        project_id = _m2o_id(task["project_id"])
        assert project_id is not None
        if not self.settings.enable_hard_delete:
            raise AccessDeniedError(
                "Hard delete is disabled; use archive_task or set ODOO_ENABLE_HARD_DELETE=true"
            )
        if confirmation != f"DELETE TASK {task_id}":
            raise ValidationError(f"confirmation must exactly equal DELETE TASK {task_id}")
        self.client.unlink("project.task", [task_id])
        self._audit("delete", "project.task", [task_id], project_id)
        return {"deleted": True, "task_id": task_id, "project_id": project_id}

    def add_task_comment(self, task_id: int, body: str) -> dict[str, Any]:
        task = self._task(task_id)
        project_id = _m2o_id(task["project_id"])
        assert project_id is not None
        self._require_text(body, "body", 100_000)
        message_id = self.client.execute(
            "project.task",
            "message_post",
            [[task_id]],
            {"body": body, "message_type": "comment", "subtype_xmlid": "mail.mt_comment"},
        )
        self._audit("comment", "project.task", [task_id], project_id)
        return {"task_id": task_id, "message_id": int(message_id)}

    def workload(self, project_id: int) -> dict[str, Any]:
        self._project(project_id)
        tasks = self.client.search_read(
            "project.task",
            [["project_id", "=", project_id], ["active", "=", True]],
            self._readable_fields("project.task", ["id", "user_ids", "allocated_hours"]),
            limit=500,
            order="id asc",
        )
        users = {user["id"]: user for user in self.list_assignable_users(limit=200)}
        totals: dict[int | None, dict[str, Any]] = {}
        for task in tasks:
            assignees = task.get("user_ids") or [None]
            share = float(task.get("allocated_hours") or 0) / max(len(assignees), 1)
            for user_id in assignees:
                bucket = totals.setdefault(
                    user_id,
                    {
                        "user_id": user_id,
                        "user_name": users.get(user_id, {}).get("name")
                        if user_id
                        else "Unassigned",
                        "task_count": 0,
                        "allocated_hours_share": 0.0,
                    },
                )
                bucket["task_count"] += 1
                bucket["allocated_hours_share"] = round(bucket["allocated_hours_share"] + share, 2)
        return {
            "project_id": project_id,
            "people": sorted(
                totals.values(),
                key=lambda row: (-row["allocated_hours_share"], str(row["user_name"])),
            ),
            "returned_task_count": len(tasks),
            "possibly_truncated": len(tasks) == 500,
        }

    # Tags -------------------------------------------------------------------

    def list_tags(self, project_id: int) -> list[dict[str, Any]]:
        self._project(project_id)
        return self.client.search_read(
            "project.tags",
            ["|", ["project_ids", "=", False], ["project_ids", "in", [project_id]]],
            self._readable_fields("project.tags", TAG_FIELDS),
            limit=200,
            order="name asc, id asc",
        )

    def create_tag(self, project_id: int, name: str, color: int = 0) -> dict[str, Any]:
        self._project(project_id)
        self._require_text(name, "name", 255)
        if not 0 <= color <= 11:
            raise ValidationError("color must be an Odoo color index from 0 to 11")
        tag_id = self.client.create(
            "project.tags",
            {"name": name.strip(), "color": color, "project_ids": [[6, 0, [project_id]]]},
        )
        self._audit("create", "project.tags", [tag_id], project_id)
        return self._tag(tag_id, project_id)

    def set_task_tags(self, task_id: int, tag_ids: Iterable[int]) -> dict[str, Any]:
        return self.update_task(task_id, {"tag_ids": list(tag_ids)})

    # Milestones -------------------------------------------------------------

    def list_milestones(self, project_id: int) -> list[dict[str, Any]]:
        self._project(project_id)
        return self.client.search_read(
            "project.milestone",
            [["project_id", "=", project_id]],
            self._readable_fields("project.milestone", MILESTONE_FIELDS),
            limit=200,
            order="deadline asc, id asc",
        )

    def create_milestone(
        self, project_id: int, name: str, *, deadline: str | None = None
    ) -> dict[str, Any]:
        project = self._project(project_id)
        if not project.get("allow_milestones"):
            raise ValidationError("Milestones are disabled on this project")
        self._require_text(name, "name", 255)
        values: dict[str, Any] = {"project_id": project_id, "name": name.strip()}
        if deadline is not None:
            values["deadline"] = _date_value(deadline, "deadline")
        milestone_id = self.client.create("project.milestone", values)
        self._audit("create", "project.milestone", [milestone_id], project_id)
        return self._milestone(milestone_id, project_id)

    def update_milestone(self, milestone_id: int, changes: dict[str, Any]) -> dict[str, Any]:
        milestone = self._milestone(milestone_id)
        project_id = _m2o_id(milestone["project_id"])
        assert project_id is not None
        self._reject_unknown(changes, {"name", "deadline", "is_reached"})
        values = dict(changes)
        if "name" in values:
            self._require_text(values["name"], "name", 255)
            values["name"] = values["name"].strip()
        if "deadline" in values:
            values["deadline"] = _date_value(values["deadline"], "deadline")
        if not values:
            raise ValidationError("No milestone changes were supplied")
        self.client.write("project.milestone", [milestone_id], values)
        self._audit("update", "project.milestone", [milestone_id], project_id, values.keys())
        return self._milestone(milestone_id, project_id)

    # Timesheets (official optional hr_timesheet feature) --------------------

    def list_timesheets(
        self,
        project_id: int,
        *,
        task_id: int | None = None,
        user_id: int | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        fields = self._timesheet_fields()
        self._project(project_id)
        domain: list[Any] = [["project_id", "=", project_id]]
        if task_id is not None:
            task = self._task(task_id)
            if _m2o_id(task["project_id"]) != project_id:
                raise ValidationError("task_id is not in project_id")
            domain.append(["task_id", "=", task_id])
        if user_id is not None:
            self._validate_users([user_id])
            domain.append(["user_id", "=", user_id])
        if date_from is not None:
            domain.append(["date", ">=", _date_value(date_from, "date_from")])
        if date_to is not None:
            domain.append(["date", "<=", _date_value(date_to, "date_to")])
        readable = [
            field
            for field in [
                "id",
                "name",
                "date",
                "unit_amount",
                "project_id",
                "task_id",
                "user_id",
                "employee_id",
                "create_date",
            ]
            if field in fields
        ]
        return self.client.search_read(
            "account.analytic.line",
            domain,
            readable,
            limit=_bounded_limit(limit, 500),
            order="date desc, id desc",
        )

    def create_timesheet(
        self,
        task_id: int,
        description: str,
        hours: float,
        *,
        work_date: str | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        fields = self._timesheet_fields()
        task = self._task(task_id)
        project_id = _m2o_id(task["project_id"])
        assert project_id is not None
        self._require_text(description, "description", 10_000)
        hours = _finite_hours(hours, "hours", allow_zero=False)
        if hours > 24:
            raise ValidationError("hours must be greater than 0 and no more than 24")
        values: dict[str, Any] = {
            "task_id": task_id,
            "project_id": project_id,
            "name": description,
            "unit_amount": hours,
            "date": _date_value(work_date or date.today().isoformat(), "work_date"),
        }
        if user_id is not None:
            self._validate_users([user_id])
            if "user_id" not in fields:
                raise CapabilityUnavailableError(
                    "This timesheet model cannot assign entries by user_id"
                )
            values["user_id"] = user_id
        line_id = self.client.create("account.analytic.line", values)
        self._audit("create", "account.analytic.line", [line_id], project_id)
        return self._timesheet(line_id)

    def update_timesheet(self, line_id: int, changes: dict[str, Any]) -> dict[str, Any]:
        self._timesheet_fields()
        line = self._timesheet(line_id)
        project_id = _m2o_id(line["project_id"])
        assert project_id is not None
        self._reject_unknown(changes, {"name", "unit_amount", "date", "user_id"})
        values = dict(changes)
        if "name" in values:
            self._require_text(values["name"], "name", 10_000)
        if "unit_amount" in values:
            values["unit_amount"] = _finite_hours(
                values["unit_amount"], "unit_amount", allow_zero=False
            )
            if values["unit_amount"] > 24:
                raise ValidationError("unit_amount must be greater than 0 and no more than 24")
        if "date" in values:
            values["date"] = _date_value(values["date"], "date")
        if "user_id" in values:
            if "user_id" not in self._timesheet_fields():
                raise CapabilityUnavailableError(
                    "This timesheet model cannot assign entries by user_id"
                )
            self._validate_users([int(values["user_id"])])
        if not values:
            raise ValidationError("No timesheet changes were supplied")
        self.client.write("account.analytic.line", [line_id], values)
        self._audit("update", "account.analytic.line", [line_id], project_id, values.keys())
        return self._timesheet(line_id)

    def delete_timesheet(self, line_id: int, confirmation: str) -> dict[str, Any]:
        line = self._timesheet(line_id)
        project_id = _m2o_id(line["project_id"])
        assert project_id is not None
        if not self.settings.enable_hard_delete:
            raise AccessDeniedError("Hard delete is disabled by ODOO_ENABLE_HARD_DELETE")
        if confirmation != f"DELETE TIMESHEET {line_id}":
            raise ValidationError(f"confirmation must exactly equal DELETE TIMESHEET {line_id}")
        self.client.unlink("account.analytic.line", [line_id])
        self._audit("delete", "account.analytic.line", [line_id], project_id)
        return {"deleted": True, "timesheet_id": line_id, "project_id": project_id}

    # Record-policy helpers --------------------------------------------------

    def _project(self, project_id: int) -> dict[str, Any]:
        project_id = _positive_id(project_id, "project_id")
        self.policy.require_project(project_id)
        records = self.client.read(
            "project.project",
            [project_id],
            self._readable_fields("project.project", PROJECT_FIELDS),
        )
        if not records:
            raise AccessDeniedError("The requested project is unavailable")
        return records[0]

    def _task(self, task_id: int) -> dict[str, Any]:
        task_id = _positive_id(task_id, "task_id")
        records = self.client.read(
            "project.task", [task_id], self._readable_fields("project.task", TASK_FIELDS)
        )
        if not records:
            raise AccessDeniedError("The requested task is unavailable")
        task = records[0]
        project_id = _m2o_id(task.get("project_id"))
        if project_id is None:
            raise AccessDeniedError("Private tasks without an allowed project are not exposed")
        self.policy.require_project(project_id)
        return task

    def _stage(
        self,
        stage_id: int,
        project_id: int,
        *,
        require_exclusively_allowed: bool = False,
    ) -> dict[str, Any]:
        stage_id = _positive_id(stage_id, "stage_id")
        self.policy.require_project(project_id)
        records = self.client.read(
            "project.task.type",
            [stage_id],
            self._readable_fields("project.task.type", STAGE_FIELDS),
        )
        if not records:
            raise AccessDeniedError("The requested stage is unavailable")
        stage = records[0]
        projects = {int(value) for value in stage.get("project_ids") or []}
        if projects and project_id not in projects:
            raise AccessDeniedError("The stage is not available in the requested project")
        if require_exclusively_allowed and (
            not projects or not projects.issubset(self.policy.allowed_project_ids)
        ):
            raise AccessDeniedError(
                "Global stages or stages shared with disallowed projects cannot be edited"
            )
        return stage

    def _tag(self, tag_id: int, project_id: int) -> dict[str, Any]:
        tag_id = _positive_id(tag_id, "tag_id")
        self.policy.require_project(project_id)
        records = self.client.read(
            "project.tags", [tag_id], self._readable_fields("project.tags", TAG_FIELDS)
        )
        if not records:
            raise AccessDeniedError("The requested tag is unavailable")
        tag = records[0]
        projects = {int(value) for value in tag.get("project_ids") or []}
        if projects and project_id not in projects:
            raise AccessDeniedError("The tag is not available in the requested project")
        return tag

    def _milestone(self, milestone_id: int, project_id: int | None = None) -> dict[str, Any]:
        milestone_id = _positive_id(milestone_id, "milestone_id")
        records = self.client.read(
            "project.milestone",
            [milestone_id],
            self._readable_fields("project.milestone", MILESTONE_FIELDS),
        )
        if not records:
            raise AccessDeniedError("The requested milestone is unavailable")
        milestone = records[0]
        actual_project = _m2o_id(milestone.get("project_id"))
        if actual_project is None:
            raise AccessDeniedError("The requested milestone has no allowed project")
        self.policy.require_project(actual_project)
        if project_id is not None and actual_project != project_id:
            raise ValidationError("milestone_id is not in project_id")
        return milestone

    def _timesheet(self, line_id: int) -> dict[str, Any]:
        fields = self._timesheet_fields()
        readable = [
            field
            for field in [
                "id",
                "name",
                "date",
                "unit_amount",
                "project_id",
                "task_id",
                "user_id",
                "employee_id",
                "create_date",
            ]
            if field in fields
        ]
        records = self.client.read(
            "account.analytic.line", [_positive_id(line_id, "line_id")], readable
        )
        if not records:
            raise AccessDeniedError("The requested timesheet entry is unavailable")
        line = records[0]
        project_id = _m2o_id(line.get("project_id"))
        if project_id is None:
            raise AccessDeniedError("The requested timesheet entry has no allowed project")
        self.policy.require_project(project_id)
        return line

    def _timesheet_fields(self) -> frozenset[str]:
        if self._timesheet_fields_cache is not None:
            return self._timesheet_fields_cache
        required = {"id", "name", "date", "unit_amount", "project_id", "task_id"}
        requested = sorted(required | {"user_id", "employee_id", "create_date"})
        try:
            metadata = self.client.fields_get("account.analytic.line", requested)
        except OdooRPCError as exc:
            raise CapabilityUnavailableError(
                "Official Odoo Timesheets is unavailable or the service account lacks access"
            ) from exc
        available = frozenset(metadata)
        if not required.issubset(available):
            raise CapabilityUnavailableError(
                "Install/enable the official Odoo Timesheets feature (hr_timesheet) for task timesheets"
            )
        self._timesheet_fields_cache = available
        return available

    def _readable_fields(self, model: str, requested: Iterable[str]) -> list[str]:
        """Return only fields visible to the service account, preserving order."""
        requested_tuple = tuple(requested)
        key = (model, requested_tuple)
        if key not in self._readable_fields_cache:
            metadata = self.client.fields_get(model, list(requested_tuple))
            readable = tuple(field for field in requested_tuple if field in metadata)
            if "id" in requested_tuple and "id" not in readable:
                raise CapabilityUnavailableError(f"Odoo did not expose required {model}.id field")
            self._readable_fields_cache[key] = readable
        return list(self._readable_fields_cache[key])

    def _validate_users(self, values: Iterable[int]) -> list[int]:
        ids = sorted({_positive_id(int(value), "assignee_user_id") for value in values})
        self.policy.require_assignees(ids)
        if not ids:
            return []
        records = self.client.search_read(
            "res.users",
            [["id", "in", ids], ["active", "=", True], ["share", "=", False]],
            ["id"],
            limit=len(ids),
        )
        found = {record["id"] for record in records}
        if found != set(ids):
            raise ValidationError("Every assignee must be an active internal Odoo user")
        return ids

    def _validate_tags(self, values: Iterable[int], project_id: int) -> list[int]:
        ids = sorted({_positive_id(int(value), "tag_id") for value in values})
        for tag_id in ids:
            self._tag(tag_id, project_id)
        return ids

    def _validate_tasks_in_project(self, values: Iterable[int], project_id: int) -> list[int]:
        ids = sorted({_positive_id(int(value), "task_id") for value in values})
        for task_id in ids:
            task = self._task(task_id)
            if _m2o_id(task["project_id"]) != project_id:
                raise ValidationError("Related tasks must belong to the same project")
        return ids

    def _selection(self, model: str, field: str) -> dict[str, str]:
        key = (model, field)
        if key not in self._selection_cache:
            metadata = self.client.fields_get(model, [field]).get(field, {})
            selection = metadata.get("selection") or []
            self._selection_cache[key] = {str(value): str(label) for value, label in selection}
        return self._selection_cache[key]

    def _validate_selection(self, model: str, field: str, value: str) -> None:
        choices = self._selection(model, field)
        if value not in choices:
            raise ValidationError(
                f"Invalid {field!r}; allowed values: {', '.join(sorted(choices))}"
            )

    @staticmethod
    def _require_text(value: Any, name: str, maximum: int) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"{name} must be a non-empty string")
        if len(value) > maximum:
            raise ValidationError(f"{name} cannot exceed {maximum} characters")

    @staticmethod
    def _reject_unknown(changes: dict[str, Any], allowed: set[str]) -> None:
        unknown = set(changes) - allowed
        if unknown:
            raise ValidationError(f"Unsupported fields: {', '.join(sorted(unknown))}")

    def _audit(
        self,
        action: str,
        model: str,
        record_ids: list[int],
        project_id: int,
        fields: Iterable[str] = (),
    ) -> None:
        logger.info(
            "audit %s",
            json.dumps(
                {
                    "action": action,
                    "model": model,
                    "record_ids": record_ids,
                    "project_id": project_id,
                    "fields": sorted(fields),
                    "odoo_uid": self.client.uid,
                },
                separators=(",", ":"),
            ),
        )
