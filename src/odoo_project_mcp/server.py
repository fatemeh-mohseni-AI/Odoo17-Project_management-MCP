"""MCP tool registration for the Odoo 17 Project integration."""

from __future__ import annotations

import asyncio
import logging
import os
from functools import lru_cache
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from . import __version__
from .config import Settings
from .http_transport import run_http_server
from .odoo import OdooClient
from .policy import AccessPolicy
from .service import ProjectService

INSTRUCTIONS = (
    "Manage only Odoo 17 Project records allowed by this server's policy. For large projects, list "
    "stages first and retrieve tasks one stage at a time with stage_name, limit, and offset; do not "
    "load the full board. Task lists are compact; call get_task only for selected task details. Read "
    "users and tags before planning writes. Use Odoo record IDs returned by tools; never "
    "guess IDs. Prefer archive_task to delete_task. Hard deletes require both server configuration "
    "and the exact per-record confirmation phrase. Stage (Kanban column) and task state are separate. "
    "Timesheet tools require the official Odoo Timesheets feature."
)

READ_TOOL = ToolAnnotations(read_only_hint=True, open_world_hint=False)
CREATE_TOOL = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
)
UPDATE_TOOL = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)
DELETE_TOOL = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False
)

mcp = MCPServer(
    "Odoo 17 Project Management",
    version=__version__,
    instructions=INSTRUCTIONS,
)


@lru_cache(maxsize=1)
def get_service() -> ProjectService:
    settings = Settings.from_env()
    logging.getLogger().setLevel(settings.log_level)
    return ProjectService(OdooClient(settings), AccessPolicy(settings), settings)


async def _run(method: str, *args: Any, **kwargs: Any) -> Any:
    function = getattr(get_service(), method)
    return await asyncio.to_thread(function, *args, **kwargs)


@mcp.tool(annotations=READ_TOOL)
async def check_odoo_connection() -> dict[str, Any]:
    """Check Odoo 17 authentication, optional capabilities, policy, and model permissions."""
    return await _run("health")


@mcp.tool(annotations=READ_TOOL)
async def list_allowed_projects() -> list[dict[str, Any]]:
    """List only projects in the configured MCP allowlist."""
    return await _run("list_projects")


@mcp.tool(annotations=READ_TOOL)
async def get_project(project_id: int) -> dict[str, Any]:
    """Read one allowed Odoo project and its planning settings."""
    return await _run("get_project", project_id)


@mcp.tool(annotations=CREATE_TOOL)
async def create_project(
    name: str,
    description: str | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    privacy_visibility: str = "followers",
    allow_task_dependencies: bool = True,
    allow_milestones: bool = True,
    task_label: str = "Tasks",
) -> dict[str, Any]:
    """Create and policy-register a project when ODOO_ALLOW_PROJECT_CREATION is enabled."""
    return await _run(
        "create_project",
        name,
        description=description,
        date_start=date_start,
        date_end=date_end,
        privacy_visibility=privacy_visibility,
        allow_task_dependencies=allow_task_dependencies,
        allow_milestones=allow_milestones,
        task_label=task_label,
    )


@mcp.tool(annotations=UPDATE_TOOL)
async def update_project(
    project_id: int,
    name: str | None = None,
    description: str | None = None,
    clear_description: bool = False,
    date_start: str | None = None,
    clear_date_start: bool = False,
    date_end: str | None = None,
    clear_date_end: bool = False,
    privacy_visibility: str | None = None,
    allow_task_dependencies: bool | None = None,
    allow_milestones: bool | None = None,
    task_label: str | None = None,
) -> dict[str, Any]:
    """Update explicitly supplied planning fields on an allowed project."""
    changes: dict[str, Any] = {}
    for key, value in {
        "name": name,
        "privacy_visibility": privacy_visibility,
        "allow_task_dependencies": allow_task_dependencies,
        "allow_milestones": allow_milestones,
        "label_tasks": task_label,
    }.items():
        if value is not None:
            changes[key] = value
    if description is not None or clear_description:
        changes["description"] = description
    if date_start is not None or clear_date_start:
        changes["date_start"] = date_start
    if date_end is not None or clear_date_end:
        changes["date"] = date_end
    return await _run("update_project", project_id, changes)


@mcp.tool(annotations=READ_TOOL)
async def list_assignable_users(query: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """Resolve active internal Odoo users that this MCP may assign to tasks/timesheets."""
    return await _run("list_assignable_users", query, limit)


@mcp.tool(annotations=READ_TOOL)
async def list_project_stages(project_id: int) -> list[dict[str, Any]]:
    """List Kanban columns (task stages) available to an allowed project."""
    return await _run("list_stages", project_id)


@mcp.tool(annotations=CREATE_TOOL)
async def create_project_stage(
    project_id: int,
    name: str,
    sequence: int = 10,
    fold: bool = False,
    description: str | None = None,
) -> dict[str, Any]:
    """Create a Kanban column scoped to exactly one allowed project."""
    return await _run(
        "create_stage", project_id, name, sequence=sequence, fold=fold, description=description
    )


@mcp.tool(annotations=UPDATE_TOOL)
async def update_project_stage(
    project_id: int,
    stage_id: int,
    name: str | None = None,
    sequence: int | None = None,
    fold: bool | None = None,
    description: str | None = None,
    clear_description: bool = False,
) -> dict[str, Any]:
    """Edit a project-scoped stage; global or cross-policy stages are intentionally read-only."""
    changes: dict[str, Any] = {}
    for key, value in {"name": name, "sequence": sequence, "fold": fold}.items():
        if value is not None:
            changes[key] = value
    if description is not None or clear_description:
        changes["description"] = description
    return await _run("update_stage", project_id, stage_id, changes)


@mcp.tool(annotations=READ_TOOL)
async def get_project_board(
    project_id: int, include_archived: bool = False, limit: int = 50
) -> dict[str, Any]:
    """Return a compact board snapshot (max 100 tasks); prefer stage-filtered lists for large boards."""
    return await _run(
        "get_project_board", project_id, include_archived=include_archived, limit=limit
    )


@mcp.tool(annotations=READ_TOOL)
async def list_tasks(
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
    """Return compact task summaries (max 100), optionally filtered by exact column name."""
    return await _run(
        "list_tasks",
        project_id=project_id,
        query=query,
        stage_id=stage_id,
        stage_name=stage_name,
        assignee_user_id=assignee_user_id,
        tag_id=tag_id,
        parent_task_id=parent_task_id,
        deadline_before=deadline_before,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )


@mcp.tool(annotations=READ_TOOL)
async def get_task(task_id: int) -> dict[str, Any]:
    """Read one task after resolving and checking its real Odoo project."""
    return await _run("get_task", task_id)


@mcp.tool(annotations=CREATE_TOOL)
async def create_task(
    project_id: int,
    name: str,
    description: str | None = None,
    assignee_user_ids: list[int] | None = None,
    allocated_hours: float | None = None,
    stage_id: int | None = None,
    tag_ids: list[int] | None = None,
    deadline: str | None = None,
    parent_task_id: int | None = None,
    priority: str = "0",
    blocked_by_task_ids: list[int] | None = None,
    milestone_id: int | None = None,
) -> dict[str, Any]:
    """Create a task with description, assignees, estimate, stage, tags, parent and blockers."""
    return await _run(
        "create_task",
        project_id,
        name,
        description=description,
        assignee_user_ids=assignee_user_ids or [],
        allocated_hours=allocated_hours,
        stage_id=stage_id,
        tag_ids=tag_ids or [],
        deadline=deadline,
        parent_task_id=parent_task_id,
        priority=priority,
        blocked_by_task_ids=blocked_by_task_ids or [],
        milestone_id=milestone_id,
    )


@mcp.tool(annotations=CREATE_TOOL)
async def create_subtask(
    parent_task_id: int,
    name: str,
    description: str | None = None,
    assignee_user_ids: list[int] | None = None,
    allocated_hours: float | None = None,
    stage_id: int | None = None,
    tag_ids: list[int] | None = None,
    deadline: str | None = None,
    priority: str = "0",
) -> dict[str, Any]:
    """Create a subtask in the same allowed project as its verified parent task."""
    parent = await _run("get_task", parent_task_id)
    project = parent["project_id"]
    project_id = int(project[0] if isinstance(project, (list, tuple)) else project)
    return await _run(
        "create_task",
        project_id,
        name,
        description=description,
        assignee_user_ids=assignee_user_ids or [],
        allocated_hours=allocated_hours,
        stage_id=stage_id,
        tag_ids=tag_ids or [],
        deadline=deadline,
        parent_task_id=parent_task_id,
        priority=priority,
    )


@mcp.tool(annotations=UPDATE_TOOL)
async def update_task(
    task_id: int,
    name: str | None = None,
    description: str | None = None,
    clear_description: bool = False,
    assignee_user_ids: list[int] | None = None,
    clear_assignees: bool = False,
    allocated_hours: float | None = None,
    stage_id: int | None = None,
    tag_ids: list[int] | None = None,
    clear_tags: bool = False,
    deadline: str | None = None,
    clear_deadline: bool = False,
    parent_task_id: int | None = None,
    clear_parent: bool = False,
    priority: str | None = None,
    blocked_by_task_ids: list[int] | None = None,
    clear_blockers: bool = False,
    milestone_id: int | None = None,
    clear_milestone: bool = False,
) -> dict[str, Any]:
    """Update only supplied fields on an allowed task; explicit clear flags avoid accidental erasure."""
    changes: dict[str, Any] = {}
    for key, value in {
        "name": name,
        "allocated_hours": allocated_hours,
        "stage_id": stage_id,
        "priority": priority,
    }.items():
        if value is not None:
            changes[key] = value
    if description is not None or clear_description:
        changes["description"] = description
    if assignee_user_ids is not None or clear_assignees:
        changes["user_ids"] = assignee_user_ids or []
    if tag_ids is not None or clear_tags:
        changes["tag_ids"] = tag_ids or []
    if deadline is not None or clear_deadline:
        changes["date_deadline"] = deadline
    if parent_task_id is not None or clear_parent:
        changes["parent_id"] = parent_task_id
    if blocked_by_task_ids is not None or clear_blockers:
        changes["depend_on_ids"] = blocked_by_task_ids or []
    if milestone_id is not None or clear_milestone:
        changes["milestone_id"] = milestone_id
    return await _run("update_task", task_id, changes)


@mcp.tool(annotations=UPDATE_TOOL)
async def move_task_to_stage(task_id: int, stage_id: int) -> dict[str, Any]:
    """Move a task to an allowed Kanban column after validating task and stage projects."""
    return await _run("move_task", task_id, stage_id)


@mcp.tool(annotations=READ_TOOL)
async def list_task_states() -> list[dict[str, str]]:
    """List live Odoo 17 task state keys; task state is separate from the Kanban stage."""
    return await _run("list_task_states")


@mcp.tool(annotations=UPDATE_TOOL)
async def set_task_state(task_id: int, state: str) -> dict[str, Any]:
    """Set a task's Odoo state using a key returned by list_task_states."""
    return await _run("set_task_state", task_id, state)


@mcp.tool(annotations=UPDATE_TOOL)
async def archive_task(task_id: int, archived: bool = True) -> dict[str, Any]:
    """Archive or unarchive a task; this is the preferred reversible alternative to deletion."""
    return await _run("archive_task", task_id, archived)


@mcp.tool(annotations=DELETE_TOOL)
async def delete_task(task_id: int, confirmation: str) -> dict[str, Any]:
    """Permanently delete a task. Requires hard-delete config and confirmation 'DELETE TASK <id>'."""
    return await _run("delete_task", task_id, confirmation)


@mcp.tool(annotations=CREATE_TOOL)
async def add_task_comment(task_id: int, body: str) -> dict[str, Any]:
    """Post a comment to an allowed task's Odoo chatter as the configured service account."""
    return await _run("add_task_comment", task_id, body)


@mcp.tool(annotations=READ_TOOL)
async def get_project_workload(project_id: int) -> dict[str, Any]:
    """Summarize active task counts and estimated-hour shares by assignee for planning."""
    return await _run("workload", project_id)


@mcp.tool(annotations=READ_TOOL)
async def list_project_tags(project_id: int) -> list[dict[str, Any]]:
    """List global and project-specific task tags available to an allowed project."""
    return await _run("list_tags", project_id)


@mcp.tool(annotations=CREATE_TOOL)
async def create_project_tag(project_id: int, name: str, color: int = 0) -> dict[str, Any]:
    """Create an Odoo tag scoped to one allowed project."""
    return await _run("create_tag", project_id, name, color)


@mcp.tool(annotations=UPDATE_TOOL)
async def set_task_tags(task_id: int, tag_ids: list[int]) -> dict[str, Any]:
    """Replace a task's complete tag set with validated global/project tags."""
    return await _run("set_task_tags", task_id, tag_ids)


@mcp.tool(annotations=READ_TOOL)
async def list_project_milestones(project_id: int) -> list[dict[str, Any]]:
    """List milestones for one allowed project."""
    return await _run("list_milestones", project_id)


@mcp.tool(annotations=CREATE_TOOL)
async def create_project_milestone(
    project_id: int, name: str, deadline: str | None = None
) -> dict[str, Any]:
    """Create a milestone when milestones are enabled on the allowed project."""
    return await _run("create_milestone", project_id, name, deadline=deadline)


@mcp.tool(annotations=UPDATE_TOOL)
async def update_project_milestone(
    milestone_id: int,
    name: str | None = None,
    deadline: str | None = None,
    clear_deadline: bool = False,
    is_reached: bool | None = None,
) -> dict[str, Any]:
    """Update the name, deadline, or reached flag of an allowed-project milestone."""
    changes: dict[str, Any] = {}
    if name is not None:
        changes["name"] = name
    if deadline is not None or clear_deadline:
        changes["deadline"] = deadline
    if is_reached is not None:
        changes["is_reached"] = is_reached
    return await _run("update_milestone", milestone_id, changes)


@mcp.tool(annotations=READ_TOOL)
async def list_timesheets(
    project_id: int,
    task_id: int | None = None,
    user_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """List official Odoo Timesheets entries, restricted to an allowed project/task."""
    return await _run(
        "list_timesheets",
        project_id,
        task_id=task_id,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )


@mcp.tool(annotations=CREATE_TOOL)
async def create_timesheet(
    task_id: int,
    description: str,
    hours: float,
    work_date: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Log time on an allowed task using the official Timesheets feature."""
    return await _run(
        "create_timesheet",
        task_id,
        description,
        hours,
        work_date=work_date,
        user_id=user_id,
    )


@mcp.tool(annotations=UPDATE_TOOL)
async def update_timesheet(
    line_id: int,
    description: str | None = None,
    hours: float | None = None,
    work_date: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Update supplied fields on a verified allowed-project timesheet entry."""
    changes: dict[str, Any] = {}
    for key, value in {
        "name": description,
        "unit_amount": hours,
        "date": work_date,
        "user_id": user_id,
    }.items():
        if value is not None:
            changes[key] = value
    return await _run("update_timesheet", line_id, changes)


@mcp.tool(annotations=DELETE_TOOL)
async def delete_timesheet(line_id: int, confirmation: str) -> dict[str, Any]:
    """Permanently delete time. Requires hard-delete config and 'DELETE TIMESHEET <id>'."""
    return await _run("delete_timesheet", line_id, confirmation)


def main() -> None:
    """Run Streamable HTTP by default, or legacy stdio when explicitly selected."""
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = Settings.from_env()
    if settings.mcp_transport == "stdio":
        mcp.run("stdio")
    else:
        run_http_server(mcp, settings)


if __name__ == "__main__":
    main()
