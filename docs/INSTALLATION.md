# Installation and Codex connection

Two installation methods are supported:

1. **Docker (recommended):** isolates dependencies and is the preferred deployment for Codex and
   self-hosted Odoo.
2. **Local Python:** installs the MCP into a local Python virtual environment with `uv`.

## Before installation: prepare Odoo 17

1. Install the official **Project** application.
2. If task time entries are needed, enable the official **Timesheets** feature/application. The MCP
   detects the required `account.analytic.line.task_id` and `project_id` fields at runtime.
3. Create a dedicated **internal** Odoo user for the integration. Do not use a portal user and do
   not reuse a human administrator's account.
4. Grant the minimum Project access needed for the enabled tools. Creating projects or configuring
   stages normally requires broader Project administration rights than working on existing tasks.
5. Add the service user only to the projects it should access. For strict isolation, add Odoo record
   rules matching the MCP allowlist as a second independent boundary.
6. Generate an API key for that user, or set a local password if API keys are unavailable. Prefer an
   API key and store it in `ODOO_API_KEY`.

All creates and edits are attributed to this Odoo service user. The MCP does not impersonate a
developer by writing `create_uid`; developers are assigned through the official task `user_ids`
field.

## Method 1 (recommended): Docker

### 1.1 Clone and configure

```bash
git clone https://github.com/fatemeh-mohseni-AI/Odoo17-Project_management-MCP.git
cd Odoo17-Project_management-MCP
cp .env.example .env
```

Edit `.env`. When Odoo and the MCP share a Docker network, use the Odoo service/container DNS name,
not `localhost`:

```dotenv
ODOO_URL=http://odoo:8069
ODOO_DB=company
ODOO_USERNAME=ai-project-service@example.com
ODOO_API_KEY=replace-me
ODOO_ALLOWED_PROJECT_IDS=12,34
ODOO_ALLOWED_ASSIGNEE_USER_IDS=7,19
```

Protect the file:

```bash
chmod 600 .env
```

Find the Docker network used by Odoo:

```bash
docker inspect <odoo-container-name> \
  --format '{{range $name, $network := .NetworkSettings.Networks}}{{$name}} {{end}}'
```

Export that network name for Docker Compose. `odoo_default` is only an example/default:

```bash
export ODOO_DOCKER_NETWORK=odoo_default
```

### 1.2 Build the image

The recommended Compose command builds the local image `odoo17-project-mcp:local`:

```bash
docker compose build
```

The equivalent plain Docker command is:

```bash
docker build -t odoo17-project-mcp:local .
docker volume create odoo17_project_mcp_state
```

The image runs as a non-root user. The named volume keeps the allowlist state for projects created
through the optional `create_project` feature.

### 1.3 Check Odoo and discover database IDs

Run the administrator utility inside the built image:

```bash
docker compose run --rm \
  --entrypoint odoo-project-mcp-admin \
  odoo-project-mcp check

docker compose run --rm \
  --entrypoint odoo-project-mcp-admin \
  odoo-project-mcp discover-projects

docker compose run --rm \
  --entrypoint odoo-project-mcp-admin \
  odoo-project-mcp discover-users
```

`discover-projects` and `discover-users` are read-only administrator commands and are not exposed
as MCP tools. Put only the selected IDs in `.env`:

```dotenv
ODOO_ALLOWED_PROJECT_IDS=12,34
ODOO_ALLOWED_ASSIGNEE_USER_IDS=7,19
```

The assignee allowlist is optional. The project allowlist is mandatory unless the explicit
creation-only bootstrap is enabled. Re-run the connection check after changing `.env`.

### 1.4 Run the Dockerized MCP server

For a manual stdio smoke test:

```bash
docker compose run --rm -T odoo-project-mcp
```

The command waits silently for MCP messages on stdin. Stop it with `Ctrl+C`. The `-T` flag prevents
Docker Compose from inserting a pseudo-terminal into the MCP protocol stream.

The equivalent plain Docker run command is:

```bash
docker run --rm -i \
  --network "$ODOO_DOCKER_NETWORK" \
  --env-file "$PWD/.env" \
  -v odoo17_project_mcp_state:/data \
  odoo17-project-mcp:local
```

### 1.5 Connect Codex to the Dockerized server

Codex stores MCP settings in `~/.codex/config.toml`. Use absolute paths:

```toml
[mcp_servers.odoo_project]
command = "docker"
args = [
  "run", "--rm", "-i",
  "--network", "odoo_default",
  "--env-file", "/absolute/path/to/Odoo17-Project_management-MCP/.env",
  "-v", "odoo17_project_mcp_state:/data",
  "odoo17-project-mcp:local",
]
enabled = true
required = true
startup_timeout_sec = 30
tool_timeout_sec = 120
default_tools_approval_mode = "writes"

[mcp_servers.odoo_project.tools.delete_task]
approval_mode = "prompt"

[mcp_servers.odoo_project.tools.delete_timesheet]
approval_mode = "prompt"
```

This keeps Odoo credentials out of `config.toml`; Docker reads the mode-`0600` `.env` file. The
delete tools also remain disabled inside the MCP unless `ODOO_ENABLE_HARD_DELETE=true`.

The equivalent CLI registration is:

```bash
codex mcp add odoo_project -- \
  docker run --rm -i \
  --network odoo_default \
  --env-file /absolute/path/to/Odoo17-Project_management-MCP/.env \
  -v odoo17_project_mcp_state:/data \
  odoo17-project-mcp:local
```

After editing the configuration, restart the Codex client. Verify with:

```bash
codex mcp list
```

In the Codex terminal UI, desktop app or IDE extension, `/mcp` shows the connected server and its
tools.

## Method 2: Local Python with `uv`

### 2.1 Install locally

Requirements: Python 3.11+ and `uv`.

```bash
git clone https://github.com/fatemeh-mohseni-AI/Odoo17-Project_management-MCP.git
cd Odoo17-Project_management-MCP
cp .env.example .env
uv sync --extra dev
```

For a local process talking to an Odoo container with port `8069` published on the host, use:

```dotenv
ODOO_URL=http://127.0.0.1:8069
ODOO_STATE_FILE=./state.json
```

Load the protected `.env`, check the connection and discover IDs:

```bash
chmod 600 .env
set -a
. ./.env
set +a
uv run odoo-project-mcp-admin check
uv run odoo-project-mcp-admin discover-projects
uv run odoo-project-mcp-admin discover-users
```

Update `ODOO_ALLOWED_PROJECT_IDS` and the optional `ODOO_ALLOWED_ASSIGNEE_USER_IDS` in `.env`, then
reload it and test:

```bash
set -a
. ./.env
set +a
uv run pytest
uv run odoo-project-mcp-admin check
```

### 2.2 Connect Codex to the local Python process

Use the installed executable directly and forward already-exported environment variables:

```toml
[mcp_servers.odoo_project]
command = "/absolute/path/to/Odoo17-Project_management-MCP/.venv/bin/odoo-project-mcp"
env_vars = [
  "ODOO_URL",
  "ODOO_DB",
  "ODOO_USERNAME",
  "ODOO_API_KEY",
  "ODOO_ALLOWED_PROJECT_IDS",
  "ODOO_ALLOWED_ASSIGNEE_USER_IDS",
  "ODOO_ALLOW_PROJECT_CREATION",
  "ODOO_ENABLE_HARD_DELETE",
  "ODOO_STATE_FILE",
]
enabled = true
required = true
startup_timeout_sec = 30
tool_timeout_sec = 120
default_tools_approval_mode = "writes"
```

Start Codex from a shell where those variables are exported. Avoid putting an API key in the
`env = { ... }` table because that stores it as plaintext in `config.toml`.

## Common configuration: feature gates and state

| Variable | Default | Purpose |
|---|---:|---|
| `ODOO_ALLOWED_PROJECT_IDS` | empty | Mandatory comma-separated project IDs |
| `ODOO_ALLOWED_ASSIGNEE_USER_IDS` | empty | Optional assignable internal-user IDs |
| `ODOO_ALLOW_PROJECT_CREATION` | `false` | Enables `create_project` |
| `ODOO_PERSIST_CREATED_PROJECTS` | `true` | Persists newly created allowed IDs |
| `ODOO_STATE_FILE` | `/data/state.json` | State file for created project IDs |
| `ODOO_ENABLE_HARD_DELETE` | `false` | Enables permanent task/timesheet deletion |
| `ODOO_VERIFY_TLS` | `true` | Validates the Odoo HTTPS certificate |
| `ODOO_TIMEOUT_SECONDS` | `30` | RPC timeout, from 1 to 300 seconds |
| `LOG_LEVEL` | `INFO` | Server log level; logs go to stderr |

With creation enabled and an empty initial project allowlist, the MCP can start only to create the
first allowed project. Each project it creates is immediately allowed. Keep `/data` on a durable
volume or manually add the returned ID to `ODOO_ALLOWED_PROJECT_IDS`.

## Suggested first session

Ask Codex to proceed in this order:

1. Call `check_odoo_connection`.
2. Call `list_allowed_projects` and select a returned ID.
3. Call `get_project_board`, `list_assignable_users` and `list_project_tags`.
4. Draft the plan for review.
5. Create/update tasks only after the plan is accepted.

## Troubleshooting

### `This server supports Odoo 17 only`

`ODOO_URL` points to another major version or a reverse proxy route serving another database.

### Connection refused from the MCP container

Inside Docker, `127.0.0.1` is the MCP container. Use the Odoo service name and attach both
containers to the same Docker network.

### Authentication works but task operations fail

Check the Project access level, project membership/followers and Odoo record rules for the service
user. `check_odoo_connection` reports model-level create/read/write/unlink rights.

### Timesheet tools say the capability is unavailable

Enable the official Timesheets feature and give the service user Timesheet rights. The base
`project` module alone may not expose `task_id` on `account.analytic.line`.

### A created project disappears from the MCP after restart

Mount a writable persistent volume at `/data`, or add its ID to `ODOO_ALLOWED_PROJECT_IDS`.

### Delete is disabled

Archive tasks by default. If permanent deletion is an accepted operational requirement, set
`ODOO_ENABLE_HARD_DELETE=true`, restart, and pass the exact confirmation phrase shown by the tool.

### Codex does not list the server

Use absolute paths, keep `-i` in the Docker command, confirm the container exits cleanly when its
stdin closes, then check `codex mcp list` and `/mcp`. Server logs must go to stderr; stdout belongs
to the MCP protocol.
