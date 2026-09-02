"""Environment-based configuration with fail-closed defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .errors import ConfigurationError


def _required(env: dict[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigurationError(f"Missing required environment variable: {name}")
    return value


def _bool(env: dict[str, str], name: str, default: bool = False) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be true or false")


def _ids(env: dict[str, str], name: str) -> frozenset[int]:
    raw = env.get(name, "").strip()
    if not raw:
        return frozenset()
    try:
        values = frozenset(int(value.strip()) for value in raw.split(",") if value.strip())
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a comma-separated list of integer IDs") from exc
    if any(value <= 0 for value in values):
        raise ConfigurationError(f"{name} may only contain positive IDs")
    return values


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings for one Odoo database and one MCP policy."""

    odoo_url: str
    database: str
    username: str
    secret: str
    allowed_project_ids: frozenset[int]
    allowed_assignee_user_ids: frozenset[int]
    allow_project_creation: bool = False
    persist_created_projects: bool = True
    enable_hard_delete: bool = False
    verify_tls: bool = True
    timeout_seconds: float = 30.0
    state_file: Path = Path("/data/state.json")
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, source: dict[str, str] | None = None) -> Settings:
        env = dict(os.environ if source is None else source)
        url = _required(env, "ODOO_URL").rstrip("/")
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ConfigurationError("ODOO_URL must be an absolute http(s) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ConfigurationError(
                "ODOO_URL must not contain credentials, a query, or a fragment"
            )

        api_key = env.get("ODOO_API_KEY", "").strip()
        password = env.get("ODOO_PASSWORD", "").strip()
        secret = api_key or password
        if not secret:
            raise ConfigurationError("Set ODOO_API_KEY (preferred) or ODOO_PASSWORD")

        allow_creation = _bool(env, "ODOO_ALLOW_PROJECT_CREATION", False)
        projects = _ids(env, "ODOO_ALLOWED_PROJECT_IDS")
        if not projects and not allow_creation:
            raise ConfigurationError(
                "ODOO_ALLOWED_PROJECT_IDS is empty; configure at least one project or explicitly "
                "enable ODOO_ALLOW_PROJECT_CREATION"
            )

        try:
            timeout = float(env.get("ODOO_TIMEOUT_SECONDS", "30"))
        except ValueError as exc:
            raise ConfigurationError("ODOO_TIMEOUT_SECONDS must be numeric") from exc
        if not 1 <= timeout <= 300:
            raise ConfigurationError("ODOO_TIMEOUT_SECONDS must be between 1 and 300")

        level = env.get("LOG_LEVEL", "INFO").strip().upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigurationError("LOG_LEVEL is invalid")

        return cls(
            odoo_url=url,
            database=_required(env, "ODOO_DB"),
            username=_required(env, "ODOO_USERNAME"),
            secret=secret,
            allowed_project_ids=projects,
            allowed_assignee_user_ids=_ids(env, "ODOO_ALLOWED_ASSIGNEE_USER_IDS"),
            allow_project_creation=allow_creation,
            persist_created_projects=_bool(env, "ODOO_PERSIST_CREATED_PROJECTS", True),
            enable_hard_delete=_bool(env, "ODOO_ENABLE_HARD_DELETE", False),
            verify_tls=_bool(env, "ODOO_VERIFY_TLS", True),
            timeout_seconds=timeout,
            state_file=Path(env.get("ODOO_STATE_FILE", "/data/state.json")),
            log_level=level,
        )
