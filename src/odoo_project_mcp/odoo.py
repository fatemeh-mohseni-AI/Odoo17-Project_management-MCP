"""Narrow XML-RPC gateway for Odoo 17's official external API."""

from __future__ import annotations

import logging
import ssl
import threading
import xmlrpc.client
from http.client import HTTPConnection, HTTPSConnection
from typing import Any

from .config import Settings
from .errors import AuthenticationError, OdooRPCError

logger = logging.getLogger(__name__)


class _TimeoutTransport(xmlrpc.client.Transport):
    def __init__(self, timeout: float):
        super().__init__()
        self.timeout = timeout

    def make_connection(self, host: str | tuple[str, dict[str, str]]) -> HTTPConnection:
        connection = super().make_connection(host)
        connection.timeout = self.timeout
        return connection


class _TimeoutSafeTransport(xmlrpc.client.SafeTransport):
    def __init__(self, timeout: float, context: ssl.SSLContext):
        super().__init__(context=context)
        self.timeout = timeout

    def make_connection(self, host: str | tuple[str, dict[str, str]]) -> HTTPSConnection:
        connection = super().make_connection(host)
        connection.timeout = self.timeout
        return connection


class OdooClient:
    """Authenticated Odoo 17 client. The public helpers map to ORM methods only."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._uid: int | None = None
        self._version: dict[str, Any] | None = None
        self._lock = threading.RLock()

        if settings.odoo_url.startswith("https://"):
            context = ssl.create_default_context()
            if not settings.verify_tls:
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            transport: xmlrpc.client.Transport = _TimeoutSafeTransport(
                settings.timeout_seconds, context
            )
        else:
            transport = _TimeoutTransport(settings.timeout_seconds)

        self._common = xmlrpc.client.ServerProxy(
            f"{settings.odoo_url}/xmlrpc/2/common",
            allow_none=True,
            use_builtin_types=True,
            transport=transport,
        )
        self._models = xmlrpc.client.ServerProxy(
            f"{settings.odoo_url}/xmlrpc/2/object",
            allow_none=True,
            use_builtin_types=True,
            transport=transport,
        )

    @property
    def uid(self) -> int:
        self.connect()
        assert self._uid is not None
        return self._uid

    @property
    def version(self) -> dict[str, Any]:
        self.connect()
        assert self._version is not None
        return dict(self._version)

    def connect(self) -> None:
        with self._lock:
            if self._uid is not None:
                return
            try:
                raw_version = self._common.version()
                if not isinstance(raw_version, dict):
                    raise AuthenticationError("Odoo returned an invalid version response")
                version: dict[str, Any] = {str(key): value for key, value in raw_version.items()}
                version_info = version.get("server_version_info", [])
                if (
                    not isinstance(version_info, (list, tuple))
                    or not version_info
                    or int(version_info[0]) != 17
                ):
                    reported = version.get("server_version", "unknown")
                    raise AuthenticationError(
                        f"This server supports Odoo 17 only; Odoo reported {reported}"
                    )
                raw_uid = self._common.authenticate(
                    self.settings.database,
                    self.settings.username,
                    self.settings.secret,
                    {},
                )
            except AuthenticationError:
                raise
            except (OSError, xmlrpc.client.Error) as exc:
                raise OdooRPCError(self._safe_error("Connection failed", exc)) from exc
            if not isinstance(raw_uid, int) or isinstance(raw_uid, bool) or raw_uid <= 0:
                raise AuthenticationError(
                    "Odoo authentication failed; check database, username, and API key"
                )
            self._uid = raw_uid
            self._version = version

    def execute(
        self,
        model: str,
        method: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        with self._lock:
            self.connect()
            try:
                return self._models.execute_kw(
                    self.settings.database,
                    self.uid,
                    self.settings.secret,
                    model,
                    method,
                    args or [],
                    kwargs or {},
                )
            except (OSError, xmlrpc.client.Error) as exc:
                raise OdooRPCError(self._safe_error(f"Odoo {model}.{method} failed", exc)) from exc

    def search_read(
        self,
        model: str,
        domain: list[Any],
        fields: list[str],
        *,
        limit: int = 100,
        offset: int = 0,
        order: str = "id asc",
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        options: dict[str, Any] = {
            "fields": fields,
            "limit": limit,
            "offset": offset,
            "order": order,
        }
        if context is not None:
            options["context"] = context
        return list(
            self.execute(
                model,
                "search_read",
                [domain],
                options,
            )
        )

    def read(self, model: str, ids: list[int], fields: list[str]) -> list[dict[str, Any]]:
        return list(self.execute(model, "read", [ids], {"fields": fields}))

    def create(self, model: str, values: dict[str, Any]) -> int:
        return int(self.execute(model, "create", [values]))

    def write(self, model: str, ids: list[int], values: dict[str, Any]) -> bool:
        return bool(self.execute(model, "write", [ids, values]))

    def unlink(self, model: str, ids: list[int]) -> bool:
        return bool(self.execute(model, "unlink", [ids]))

    def fields_get(self, model: str, fields: list[str]) -> dict[str, dict[str, Any]]:
        return dict(
            self.execute(
                model,
                "fields_get",
                [fields],
                {"attributes": ["string", "type", "required", "readonly", "selection"]},
            )
        )

    def check_access(self, model: str, operation: str) -> bool:
        return bool(
            self.execute(
                model,
                "check_access_rights",
                [operation],
                {"raise_exception": False},
            )
        )

    @staticmethod
    def _safe_error(prefix: str, exc: BaseException) -> str:
        if isinstance(exc, xmlrpc.client.Fault):
            detail = exc.faultString.splitlines()[-1]
        elif isinstance(exc, xmlrpc.client.ProtocolError):
            detail = f"HTTP {exc.errcode} {exc.errmsg}"
        else:
            detail = str(exc)
        return f"{prefix}: {detail[:500]}"
