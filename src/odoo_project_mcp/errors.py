"""Domain exceptions exposed as safe MCP tool errors."""


class OdooProjectMCPError(RuntimeError):
    """Base error for the integration."""


class ConfigurationError(OdooProjectMCPError):
    """The server configuration is missing or unsafe."""


class AuthenticationError(OdooProjectMCPError):
    """Odoo authentication failed."""


class OdooRPCError(OdooProjectMCPError):
    """Odoo rejected an RPC request or was unreachable."""


class AccessDeniedError(OdooProjectMCPError):
    """The requested record is outside the configured policy."""


class ValidationError(OdooProjectMCPError):
    """A tool argument is invalid for the current Odoo database."""


class CapabilityUnavailableError(OdooProjectMCPError):
    """An optional official Odoo capability is not installed or enabled."""
