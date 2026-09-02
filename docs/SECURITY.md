# Security and operations

## Security posture

This server is a privileged automation client. Treat an AI tool call like an API request from an
untrusted planner: validate it, constrain its authority and keep destructive operations reviewable.

The intended controls are layered:

1. A dedicated Odoo service account and Odoo ACLs/record rules.
2. A mandatory MCP project allowlist.
3. Optional MCP assignee allowlist.
4. A narrow typed tool catalog with no generic ORM escape hatch.
5. Relationship checks based on records read from Odoo.
6. Feature gates and confirmations for higher-risk operations.
7. MCP host approval policy and stderr audit logs.

No one layer should be considered sufficient on its own.

## Threats and controls

| Threat | Control |
|---|---|
| Prompt injection asks for another project | Actual record `project_id` is resolved and checked for every read/write |
| Caller guesses a task ID | Out-of-policy task is denied after project resolution and not returned |
| Caller supplies a stage/tag from another project | Cross-record project validation before task write |
| Editing a global stage affects hidden projects | Global/shared stages are usable but not editable |
| AI assigns an unexpected employee | Optional user-ID allowlist plus active internal-user validation |
| Generic Odoo data exfiltration | No caller-controlled model, method, field list or raw domain tool |
| Accidental permanent deletion | Off-by-default hard-delete flag, exact phrase and MCP destructive annotation |
| Credentials leak into output/logs | Secrets remain in settings only; errors and audit events omit them |
| Man-in-the-middle on external Odoo URL | TLS verification on by default |
| Created-project access broadens silently | Separate creation flag and explicit persisted state file |
| MCP process exposes a network service | Default/supported transport is local stdio |

## Odoo account hardening

- Create a named integration user such as `ai-project-service`; do not use the Odoo superuser.
- Use an API key with a rotation schedule. Revoke it immediately if the host or `.env` file is
  exposed.
- Grant Project User access for existing-task workflows. Grant Project Administrator only if project
  or stage creation is an accepted requirement.
- Grant Timesheet access only when timesheet tools are needed.
- Make the user a member/follower only of approved projects.
- Add server-side Odoo record rules if the service account must be technically unable to see any
  other projects, even if the MCP layer is bypassed.
- Test each required create/read/write/unlink operation in staging.

The `check_odoo_connection` tool reports coarse model permissions. It does not replace record-level
tests because Odoo rules can depend on the project and user.

## Secret handling

- Keep `.env` outside source control; it is ignored by Git.
- Set file mode `0600` and restrict the parent directory.
- In Codex, prefer Docker `--env-file` or `env_vars` over embedding secrets in `config.toml`.
- Never pass the API key as a Docker command-line `--env ODOO_API_KEY=value`; process listings may
  expose it.
- Do not enable shell debug tracing while loading the file.
- Rotate the key separately from the Odoo service user's interactive password.

## Network security

- A plain `http://odoo:8069` URL is acceptable only on a controlled private Docker network.
- Use HTTPS across hosts, VLANs or untrusted networks.
- Leave `ODOO_VERIFY_TLS=true`. If a private CA is used, add that CA to the container trust store
  instead of disabling verification.
- `ODOO_VERIFY_TLS=false` is an explicit escape hatch for testing and permits interception.
- Restrict the MCP container's egress to the Odoo host when platform controls allow it.

## Project creation and state

`ODOO_ALLOW_PROJECT_CREATION` changes the authorization boundary because a new project did not exist
in the static allowlist. It is disabled by default. If enabled:

- mount `/data` on a persistent, access-controlled volume;
- monitor `state.json` changes;
- add mature projects to the static environment allowlist;
- disable creation again if it is only needed during bootstrap.

The state file contains project IDs only, not credentials or project names. The server writes it
atomically with mode `0600`.

## Deletion policy

Use archive for normal task removal. Enable hard delete only after deciding how Odoo backups,
retention and legal/audit requirements apply.

A deletion succeeds only when:

1. the service account has Odoo `unlink` rights;
2. `ODOO_ENABLE_HARD_DELETE=true`;
3. the record belongs to an allowed project;
4. the request carries the exact phrase for that record ID;
5. the MCP host's approval policy permits the destructive tool.

Recommended Codex configuration keeps `default_tools_approval_mode = "writes"` and explicitly sets
`approval_mode = "prompt"` for both delete tools.

## Audit and monitoring

Collect container stderr into a restricted log system. Alert on:

- `delete` actions;
- repeated access denials or authentication failures;
- project creation;
- changes in the effective allowed-project list;
- unusual write volume from the service account.

Audit events contain action, model, record IDs, project ID, changed field names and authenticated
Odoo UID. They intentionally exclude descriptions, comments, task names and credentials.

## Incident response

If misuse is suspected:

1. Stop/disable the MCP server in Codex.
2. Revoke the Odoo API key.
3. Preserve stderr audit logs and Odoo chatter/audit history.
4. Review task/project changes and restore from backup when required.
5. Inspect Odoo ACLs, record rules, static allowlists and the created-project state file.
6. Issue a new API key only after the root cause is fixed.

Report product vulnerabilities using the private process described in the repository's root
`SECURITY.md`.

