# MCP tool catalog

The server registers 32 typed tools. Read tools are annotated read-only; create/update tools are
non-destructive writes; permanent deletion is annotated destructive. All record tools are subject to
Odoo permissions and the MCP project policy.

## Connection and lookup

| Tool | Purpose |
|---|---|
| `check_odoo_connection` | Authenticate, enforce Odoo 17, report model permissions and optional capabilities |
| `list_allowed_projects` | List only effective allowed projects |
| `list_assignable_users` | Resolve active internal users, filtered by optional assignee allowlist |

## Projects and board columns

| Tool | Purpose |
|---|---|
| `get_project` | Read one allowed project and planning flags |
| `create_project` | Create and policy-register a project; requires `ODOO_ALLOW_PROJECT_CREATION=true` |
| `update_project` | Update explicit safe project fields |
| `list_project_stages` | List project-specific and global Kanban columns |
| `create_project_stage` | Create a stage scoped to one project |
| `update_project_stage` | Rename/reorder/fold a safely scoped stage |
| `get_project_board` | Return a compact snapshot capped at 100 tasks; avoid for large projects |

Global stages and stages shared with a disallowed project can be listed and used for movement but
cannot be edited through this server.

## Tasks and planning

| Tool | Purpose |
|---|---|
| `list_tasks` | Compact, paginated task summaries; exact `stage_name` or `stage_id` filter runs in Odoo |
| `get_task` | Read a task after checking its actual project |
| `create_task` | Create with description, developer(s), estimate, stage, tags, deadline, priority, parent, milestone and blockers |
| `create_subtask` | Create in the verified parent task's project |
| `update_task` | Edit supplied fields; `clear_*` flags explicitly erase optional data |
| `move_task_to_stage` | Change Backlog/In Progress/etc. board column |
| `list_task_states` | Read live `project.task.state` keys and labels |
| `set_task_state` | Set state using a returned live key |
| `archive_task` | Reversibly archive or unarchive |
| `delete_task` | Permanent delete with feature gate and `DELETE TASK <id>` confirmation |
| `add_task_comment` | Post an Odoo chatter comment as the service account |
| `get_project_workload` | Summarize task counts and allocated-hour shares by assignee |

`move_task_to_stage` and `set_task_state` are intentionally separate: an Odoo board stage is not the
same field as Odoo's task state.

## Tags

| Tool | Purpose |
|---|---|
| `list_project_tags` | List global/project tags available to a project |
| `create_project_tag` | Create a project-scoped tag |
| `set_task_tags` | Replace the task's complete tag set after validation |

## Milestones

| Tool | Purpose |
|---|---|
| `list_project_milestones` | List milestones for a project |
| `create_project_milestone` | Create when milestones are enabled |
| `update_project_milestone` | Update name, deadline or reached flag |

## Timesheets

These tools require the official Timesheets feature and the service user's Timesheet permissions.

| Tool | Purpose |
|---|---|
| `list_timesheets` | List time entries inside one allowed project/task/date/user filter |
| `create_timesheet` | Log `0 < hours <= 24` on an allowed task |
| `update_timesheet` | Update description, hours, date or user |
| `delete_timesheet` | Permanent delete with feature gate and `DELETE TIMESHEET <id>` confirmation |

## Recommended planning workflow

1. `check_odoo_connection`
2. `list_allowed_projects`
3. `list_project_stages`
4. For each needed column, call `list_tasks` with `project_id`, exact `stage_name`, `limit=25`, and
   successive `offset` values only when another page is needed
5. Call `get_task` only for tasks whose full description or dependency details are required
6. `list_assignable_users`, `list_project_tags`, and optionally `list_project_milestones`
7. Present a proposed plan to the user and use create/update tools after approval
8. Read only the affected stage/task again to verify the result

`stage_name` is an intentional exception to the ID-first rule: the server resolves an exact,
case-insensitive name only within the selected project and fails if it is absent or ambiguous. For
writes, continue to use IDs returned by lookup tools and never guess database IDs.

`list_tasks` defaults to 25 rows and accepts at most 100. Its summary omits `description`, dependency
ID arrays, stage-change dates and create/write timestamps. `get_task` remains the full-detail tool.
