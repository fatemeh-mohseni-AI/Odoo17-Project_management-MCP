# Odoo 17 Project Management MCP

A security-focused Model Context Protocol server that lets Codex and other MCP hosts plan and
manage work in the **official Odoo 17 Project application**. It supports self-hosted Odoo,
including Docker deployments, and communicates through Odoo's documented XML-RPC external API.

> Status: alpha (`0.1.0`). Test against a staging Odoo database before enabling writes in
> production.

[راهنمای فارسی](README.fa.md) · [Installation](docs/INSTALLATION.md) ·
[Technical architecture](docs/TECHNICAL.md) · [Tool catalog](docs/TOOLS.md) ·
[Security](docs/SECURITY.md)

## What it supports

| Area | Capabilities |
|---|---|
| Access boundary | Mandatory project-ID allowlist; optional assignee allowlist; every indirect record is re-checked |
| Projects | List, read, create (feature-gated), update dates, visibility and planning settings |
| Board columns | List, create, reorder and edit project-scoped task stages; safe read-only handling of global stages |
| Tasks | Search, read, create, update, move, archive/unarchive and hard-delete with two safety gates |
| Planning | Assignees, allocated-hour estimates, deadlines, priority, workload summary, dependencies and blockers |
| Structure | Subtasks and milestones |
| Classification | List/create project tags and replace a task's tag set |
| Collaboration | Post task chatter comments as the configured service account |
| Status | Change the Kanban stage or Odoo task state; live state values are introspected from Odoo |
| Time tracking | List, create, update and delete entries when the official Odoo Timesheets feature is installed |
| Operations | Odoo 17 version check, permission/capability check, structured audit logs, Docker image and CI |

There is deliberately **no generic `execute_kw`, model, domain, field or method tool**. The model
cannot turn this server into unrestricted access to the rest of Odoo.

## Quick start

Requirements: Python 3.11+, [`uv`](https://docs.astral.sh/uv/) and an Odoo 17 service account.

```bash
git clone https://github.com/fatemeh-mohseni-AI/Odoo17-Project_management-MCP.git
cd Odoo17-Project_management-MCP
cp .env.example .env
uv sync --extra dev
```

Set the connection variables, then discover stable Odoo database IDs from your administrator
terminal. Discovery commands are intentionally not MCP tools.

```bash
set -a
. ./.env
set +a
uv run odoo-project-mcp-admin check
uv run odoo-project-mcp-admin discover-projects
uv run odoo-project-mcp-admin discover-users
```

Put only approved IDs in `.env`:

```dotenv
ODOO_ALLOWED_PROJECT_IDS=12,34
ODOO_ALLOWED_ASSIGNEE_USER_IDS=7,19
```

Run the tests and start the stdio server:

```bash
uv run pytest
uv run odoo-project-mcp
```

The final command waits silently for MCP messages on stdin; that is expected. Follow the
[installation guide](docs/INSTALLATION.md) for Odoo permissions, Docker networking and complete
Codex `config.toml` examples.

## Safe defaults

- An empty project allowlist stops normal operation. A creation-only bootstrap must be explicitly
  enabled.
- Project creation is off by default.
- Permanent task and timesheet deletion is off by default. Archiving is available and preferred.
- Hard deletion additionally requires an exact record-specific confirmation phrase.
- Credentials are read from environment variables and never returned by a tool or written to logs.
- Created projects can be persisted in a mode-`0600` state file so they remain allowed after a
  container restart.
- Global stages and stages shared with any disallowed project are read-only through this MCP.
- MCP uses stdio by default, so the server opens no new network listener.

The MCP allowlist is a second boundary, not a replacement for Odoo access controls. Give the
service account the least Odoo permissions it needs and restrict it to the same projects.

## Compatibility and scope

- Supported Odoo major version: **17 only**. Startup authentication rejects other major versions.
- Supported Odoo deployment: self-hosted packages or Docker, reachable over HTTP(S).
- Supported app scope: official `project` models and directly related official features.
- Task timesheets need the official `hr_timesheet` feature; tools report a clear capability error
  when it is absent.
- No custom Odoo module is required.
- MCP SDK line: official Python SDK `2.x`; transport: stdio.

References:

- [Odoo 17 External API](https://www.odoo.com/documentation/17.0/developer/reference/external_api.html)
- [Official Odoo Project app](https://www.odoo.com/app/project)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Codex MCP setup](https://learn.chatgpt.com/docs/extend/mcp)

## Development

```bash
make install
make lint
make test
make build
```

See [CONTRIBUTING.md](CONTRIBUTING.md). This project is licensed under the [MIT License](LICENSE).

