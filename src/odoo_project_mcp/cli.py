"""Administrator-only discovery commands. These are not exposed as MCP tools."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

from .config import Settings
from .odoo import OdooClient


def _client() -> OdooClient:
    env = dict(os.environ)
    # Discovery must work before the first project allowlist is known. This does not
    # change the MCP tool policy and only affects this local administrator process.
    env["ODOO_ALLOW_PROJECT_CREATION"] = "true"
    # This utility does not start an MCP transport, so initial discovery must
    # not require the Streamable HTTP bearer token.
    env["MCP_TRANSPORT"] = "stdio"
    return OdooClient(Settings.from_env(env))


def _print(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(description="Odoo Project MCP administrator utility")
    parser.add_argument(
        "command",
        choices=("check", "discover-projects", "discover-users"),
        help="Read-only setup command to run",
    )
    args = parser.parse_args()
    client = _client()
    if args.command == "check":
        _print({"uid": client.uid, "server_version": client.version.get("server_version")})
    elif args.command == "discover-projects":
        _print(
            client.search_read(
                "project.project",
                [],
                ["id", "name", "active", "privacy_visibility"],
                limit=1000,
                order="name asc, id asc",
            )
        )
    else:
        _print(
            client.search_read(
                "res.users",
                [["active", "=", True], ["share", "=", False]],
                ["id", "name", "login"],
                limit=1000,
                order="name asc, id asc",
            )
        )


if __name__ == "__main__":
    main()
