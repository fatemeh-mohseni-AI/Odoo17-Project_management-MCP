"""Project and assignee allowlists shared by every service operation."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path

from .config import Settings
from .errors import AccessDeniedError

logger = logging.getLogger(__name__)


class AccessPolicy:
    """Fail-closed application policy layered on top of Odoo record rules."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.RLock()
        self._created_project_ids = self._load_created_project_ids()

    @property
    def allowed_project_ids(self) -> frozenset[int]:
        with self._lock:
            return self.settings.allowed_project_ids | frozenset(self._created_project_ids)

    def require_project(self, project_id: int) -> None:
        if project_id not in self.allowed_project_ids:
            raise AccessDeniedError(
                "The requested record is unavailable or belongs to a project outside the MCP allowlist"
            )

    def require_assignees(self, user_ids: Iterable[int]) -> None:
        requested = {int(value) for value in user_ids}
        allowed = self.settings.allowed_assignee_user_ids
        if allowed and not requested.issubset(allowed):
            raise AccessDeniedError(
                "One or more assignees are outside ODOO_ALLOWED_ASSIGNEE_USER_IDS"
            )

    def remember_created_project(self, project_id: int) -> bool:
        """Allow a project created by this server; return whether it was persisted."""
        if not self.settings.allow_project_creation:
            raise AccessDeniedError("Project creation is disabled by ODOO_ALLOW_PROJECT_CREATION")
        with self._lock:
            self._created_project_ids.add(project_id)
            if not self.settings.persist_created_projects:
                return False
            try:
                self._persist()
                return True
            except OSError as exc:
                logger.error("Could not persist created project policy: %s", exc)
                return False

    def _load_created_project_ids(self) -> set[int]:
        if not self.settings.persist_created_projects:
            return set()
        path = self.settings.state_file
        if not path.exists():
            return set()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            values = {int(value) for value in payload.get("created_project_ids", [])}
            return {value for value in values if value > 0}
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            logger.error("Ignoring invalid policy state file %s: %s", path, exc)
            return set()

    def _persist(self) -> None:
        path: Path = self.settings.state_file
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            json.dumps({"created_project_ids": sorted(self._created_project_ids)}, indent=2) + "\n"
        )
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except BaseException:
            with suppress(FileNotFoundError):
                os.unlink(temporary)
            raise
