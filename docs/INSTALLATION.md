# Installation and Codex connection

The primary deployment is a long-lived Streamable HTTP service started with Docker Compose. A
local Python installation is supported as method 2. Legacy stdio is opt-in and documented last.

## Before installation: prepare Odoo 17

1. Install the official **Project** application.
2. Enable the official **Timesheets** feature if time entries are required.
3. Create a dedicated internal Odoo integration user; do not reuse an administrator account.
4. Grant only the Project/Timesheet rights required by the enabled MCP tools.
5. Restrict the service user to the same projects as the MCP allowlist, preferably with Odoo record
   rules as an independent boundary.
6. Generate an Odoo API key for the integration user.

Creates and edits are attributed to this service user. Developers are assigned through task
`user_ids`; the MCP never impersonates another creator.

## Method 1 (recommended): persistent Docker Compose service

### 1.1 Clone and create secrets

```bash
git clone https://github.com/fatemeh-mohseni-AI/Odoo17-Project_management-MCP.git
cd Odoo17-Project_management-MCP
cp .env.example .env
openssl rand -hex 32
```

Copy the generated random value into `MCP_AUTH_TOKEN`. Edit `.env`:

```dotenv
# Odoo reachable from the MCP container
ODOO_URL=http://odoo17-test:8069
ODOO_DB=mcp_test
ODOO_USERNAME=ai-project-service@example.com
ODOO_API_KEY=replace-with-the-odoo-api-key

# Database IDs, not names
ODOO_ALLOWED_PROJECT_IDS=12
ODOO_ALLOWED_ASSIGNEE_USER_IDS=7,19

# Primary MCP transport
MCP_TRANSPORT=streamable-http
MCP_HOST=0.0.0.0
MCP_PORT=31080
MCP_AUTH_TOKEN=replace-with-the-generated-64-character-value

# 0.0.0.0 permits remote access. Use 127.0.0.1 behind Nginx/Caddy.
MCP_PUBLISH_HOST=0.0.0.0

ODOO_ALLOW_PROJECT_CREATION=false
ODOO_PERSIST_CREATED_PROJECTS=true
ODOO_STATE_FILE=/data/state.json
ODOO_ENABLE_HARD_DELETE=false
ODOO_VERIFY_TLS=true
ODOO_TIMEOUT_SECONDS=30
LOG_LEVEL=INFO
```

Protect the file:

```bash
chmod 600 .env
```

### 1.2 Select the Odoo Docker network

Find the network attached to the Odoo container:

```bash
docker inspect <odoo-container-name> \
  --format '{{range $name, $network := .NetworkSettings.Networks}}{{$name}} {{end}}'
```

Export the selected network before every Compose command, or put it in the shell profile used for
deployment:

```bash
export ODOO_DOCKER_NETWORK=odoo17_mcp_test_net
```

The Odoo hostname in `ODOO_URL` must resolve on this network. Inside the MCP container,
`127.0.0.1` means the MCP container itself, not Odoo.

### 1.3 Discover project and user IDs

Build the image and run the read-only administrator utility:

```bash
docker compose build
docker compose run --rm --entrypoint odoo-project-mcp-admin odoo-project-mcp check
docker compose run --rm --entrypoint odoo-project-mcp-admin odoo-project-mcp discover-projects
docker compose run --rm --entrypoint odoo-project-mcp-admin odoo-project-mcp discover-users
```

These discovery commands deliberately run outside the MCP tool surface. They work before the
allowlist is known and do not expose unrestricted discovery to AI clients. Put only approved IDs
back into `.env`.

### 1.4 Start the persistent MCP service

Verify that the host port is not already in use:

```bash
sudo ss -lntp | grep -E ':31080\b' || echo 'port 31080 is free'
```

Start or update the service:

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 odoo-project-mcp
```

Docker restarts the service unless it is explicitly stopped. The default endpoints are:

```text
http://SERVER_IP:31080/mcp
http://SERVER_IP:31080/health
```

Test liveness locally on the server:

```bash
curl http://127.0.0.1:31080/health
```

Expected response:

```json
{"status":"ok","transport":"streamable-http","version":"0.2.0"}
```

Verify authentication behavior without printing the real token:

```bash
curl -i -X POST http://127.0.0.1:31080/mcp
curl -i -X POST -H 'Authorization: Bearer invalid' http://127.0.0.1:31080/mcp
```

The first request must return 401 and the second 403.

### 1.5 Connect Codex from another machine

On the machine running Codex, export the same bearer token under a local variable name:

```bash
export ODOO_MCP_TOKEN='the-same-secret-as-MCP_AUTH_TOKEN'
```

Do not store this token directly in `config.toml`. Add the server to `~/.codex/config.toml`:

```toml
[mcp_servers.odoo_project]
url = "http://SERVER_IP:31080/mcp"
bearer_token_env_var = "ODOO_MCP_TOKEN"
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

Restart Codex, then verify:

```bash
codex mcp list
```

Use `/mcp` in the Codex TUI or IDE extension to inspect the connected server and its tools.

### 1.6 Use HTTPS outside a trusted network

A bearer token over plain HTTP can be intercepted. Direct HTTP is acceptable only on a controlled
private network or VPN. For Internet/VLAN traffic:

1. set `MCP_PUBLISH_HOST=127.0.0.1`;
2. terminate TLS in Nginx, Caddy, or another trusted reverse proxy;
3. proxy `/mcp` without response buffering and preserve the `Authorization` header;
4. configure Codex with `https://mcp.example.com/mcp`;
5. keep the direct `31080/tcp` port closed at the firewall.

See [`deploy/nginx.conf.example`](../deploy/nginx.conf.example) for an Nginx server block.

## Method 2: local Python service

Requirements: Python 3.11+ and `uv`.

```bash
git clone https://github.com/fatemeh-mohseni-AI/Odoo17-Project_management-MCP.git
cd Odoo17-Project_management-MCP
cp .env.example .env
uv sync --extra dev
```

For a local service talking to a host-published Odoo container, configure:

```dotenv
ODOO_URL=http://127.0.0.1:8069
ODOO_STATE_FILE=./state.json
MCP_TRANSPORT=streamable-http
MCP_HOST=127.0.0.1
MCP_PORT=31080
MCP_AUTH_TOKEN=a-random-secret-with-at-least-32-characters
```

Load the environment and start the same long-lived HTTP server without Docker:

```bash
chmod 600 .env
set -a
. ./.env
set +a
uv run odoo-project-mcp-admin check
uv run odoo-project-mcp
```

Connect Codex using the URL configuration from method 1.

## Optional legacy stdio mode

The previous local-process behavior remains available for compatibility but is not the recommended
deployment. Set:

```dotenv
MCP_TRANSPORT=stdio
```

Then start `odoo-project-mcp` from the MCP host's `command`/`args` configuration. `MCP_AUTH_TOKEN`,
`MCP_HOST` and `MCP_PORT` are not used in stdio mode.

## Configuration reference

| Variable | Default | Purpose |
|---|---:|---|
| `MCP_TRANSPORT` | `streamable-http` | Primary HTTP transport or explicit legacy `stdio` |
| `MCP_HOST` | `0.0.0.0` | Interface inside the process/container |
| `MCP_PORT` | `31080` | HTTP listen/container/host port |
| `MCP_AUTH_TOKEN` | none | Required HTTP bearer token, minimum 32 characters |
| `MCP_PUBLISH_HOST` | `0.0.0.0` | Host interface used by Docker port publishing |
| `ODOO_ALLOWED_PROJECT_IDS` | empty | Mandatory comma-separated project IDs |
| `ODOO_ALLOWED_ASSIGNEE_USER_IDS` | empty | Optional assignable internal-user IDs |
| `ODOO_ALLOW_PROJECT_CREATION` | `false` | Enables `create_project` |
| `ODOO_PERSIST_CREATED_PROJECTS` | `true` | Persists newly created allowed IDs |
| `ODOO_STATE_FILE` | `/data/state.json` | Created-project state file |
| `ODOO_ENABLE_HARD_DELETE` | `false` | Enables permanent task/timesheet deletion |
| `ODOO_VERIFY_TLS` | `true` | Validates the Odoo HTTPS certificate |
| `ODOO_TIMEOUT_SECONDS` | `30` | Odoo RPC timeout from 1 to 300 seconds |
| `LOG_LEVEL` | `INFO` | Application log level |

## Suggested first Codex session

1. Call `check_odoo_connection`.
2. Call `list_allowed_projects` and choose a returned ID.
3. Call `get_project_board`, `list_assignable_users` and `list_project_tags`.
4. Draft the plan for review.
5. Create or update tasks only after the plan is accepted.
6. Prefer `archive_task`; keep permanent deletion disabled during initial testing.

## Troubleshooting

### `/health` works but `/mcp` returns 401

Codex did not inherit `ODOO_MCP_TOKEN`, or `bearer_token_env_var` names a different variable.
Export the token in the environment that launches Codex, then restart Codex.

### `/mcp` returns 403

The token sent by Codex does not exactly match `MCP_AUTH_TOKEN` in the server `.env`. Update one
side, restart the container, and restart Codex. Do not paste either token into logs or tickets.

### Connection refused

Check `docker compose ps`, the selected `MCP_PORT`, host firewall and port binding. If
`MCP_PUBLISH_HOST=127.0.0.1`, only a local reverse proxy can reach the service.

### Odoo connection refused from MCP

Check `ODOO_DOCKER_NETWORK` and use the Odoo service/container DNS name in `ODOO_URL`, not
`127.0.0.1`.

### This server supports Odoo 17 only

`ODOO_URL` points to another Odoo major version or proxy route.

### Timesheet capability unavailable

Install the official Timesheets feature and grant the integration user the required access.

### Delete is disabled

Archive tasks by default. Permanent deletion additionally requires `ODOO_ENABLE_HARD_DELETE=true`,
an exact record confirmation phrase, and host approval.
