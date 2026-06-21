"""Per-request context (request id, client IP, user agent) exposed via
contextvars so any code path — including audit logging deep in services —
can read the originating request details without threading them through
every function signature.
"""
from contextvars import ContextVar
from typing import Optional

request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
client_ip_var: ContextVar[Optional[str]] = ContextVar("client_ip", default=None)
user_agent_var: ContextVar[Optional[str]] = ContextVar("user_agent", default=None)


def set_request_context(request_id: Optional[str], client_ip: Optional[str], user_agent: Optional[str]) -> None:
    request_id_var.set(request_id)
    client_ip_var.set(client_ip)
    user_agent_var.set(user_agent)


def get_request_context() -> dict:
    return {
        "request_id": request_id_var.get(),
        "client_ip": client_ip_var.get(),
        "user_agent": user_agent_var.get(),
    }
