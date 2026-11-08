# Contributing

## Local workflow

1. Use Python 3.11 or newer and install `uv`.
2. Run `uv sync --extra dev`.
3. Create a focused branch.
4. Run `make format`, `make lint`, and `make test` before opening a pull request.

## Design constraints

- Do not expose generic Odoo models, fields, methods or caller-provided domains.
- Every record linked to a project must be resolved from Odoo and checked against `AccessPolicy`
  before it is returned or mutated.
- New write tools need accurate MCP annotations and audit events.
- Destructive tools need an off-by-default configuration gate and record-specific confirmation.
- Keep credentials and user-supplied text out of logs.
- Preserve Odoo 17-only behavior until compatibility tests exist for another major version.

Tests must cover both allowed and disallowed project paths. A happy-path test alone is not enough
for a policy boundary.

## Pull request checklist

Before opening a pull request, confirm:

- [ ] The change is focused and its purpose is explained in the PR description.
- [ ] `make format`, `make lint`, and `make test` pass, or the PR explains why a check was not run (for example, a docs-only change).
- [ ] Changes affecting records enforce project and assignee access policies, including disallowed paths.
- [ ] New write operations include appropriate MCP annotations and audit events.
- [ ] User-facing behavior or configuration changes are documented without publishing real credentials.
- [ ] Related issues are linked when applicable.
