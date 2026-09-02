"""Authenticated Streamable HTTP transport for remote MCP clients."""

from __future__ import annotations

import hmac
from typing import Any

import uvicorn
from mcp.server import MCPServer
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from . import __version__
from .config import Settings

MCP_PATH = "/mcp"
HEALTH_PATH = "/health"


class BearerAuthGateway:
    """Expose a public liveness route and protect every other HTTP route."""

    def __init__(self, application: ASGIApp, token: str) -> None:
        self.application = application
        self._token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.application(scope, receive, send)
            return

        if scope.get("path") == HEALTH_PATH:
            if scope.get("method") not in {"GET", "HEAD"}:
                response = JSONResponse({"error": "method_not_allowed"}, status_code=405)
            else:
                response = JSONResponse(
                    {
                        "status": "ok",
                        "transport": "streamable-http",
                        "version": __version__,
                    }
                )
            await response(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        raw_authorization = headers.get(b"authorization")
        if raw_authorization is None:
            await self._reject(scope, receive, send, 401, "authorization_required")
            return

        authorization = raw_authorization.decode("latin-1")
        scheme, separator, supplied_token = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not supplied_token:
            await self._reject(scope, receive, send, 401, "bearer_token_required")
            return

        if not hmac.compare_digest(supplied_token, self._token):
            await self._reject(scope, receive, send, 403, "invalid_token")
            return

        await self.application(scope, receive, send)

    @staticmethod
    async def _reject(
        scope: Scope,
        receive: Receive,
        send: Send,
        status_code: int,
        error: str,
    ) -> None:
        response = JSONResponse(
            {"error": error},
            status_code=status_code,
            headers={"WWW-Authenticate": "Bearer"},
        )
        await response(scope, receive, send)


def create_http_app(server: MCPServer[Any], settings: Settings) -> BearerAuthGateway:
    """Build the authenticated ASGI application used by Uvicorn and tests."""
    if not settings.mcp_auth_token:
        raise ValueError("MCP_AUTH_TOKEN is required for Streamable HTTP")
    application = server.streamable_http_app(
        streamable_http_path=MCP_PATH,
        host=settings.mcp_host,
    )
    return BearerAuthGateway(application, settings.mcp_auth_token)


def run_http_server(server: MCPServer[Any], settings: Settings) -> None:
    """Run the long-lived Streamable HTTP MCP service."""
    uvicorn.run(
        create_http_app(server, settings),
        host=settings.mcp_host,
        port=settings.mcp_port,
        log_level=settings.log_level.lower(),
    )
