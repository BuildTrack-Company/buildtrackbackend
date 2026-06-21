import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.shared.request_context import set_request_context


def _client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        # First entry is the original client; the rest are proxies.
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        request.state.request_id = request_id
        # Make request id, client IP and user agent available to audit logging
        # anywhere downstream in the same async task context.
        set_request_context(
            request_id,
            _client_ip(request),
            request.headers.get("user-agent"),
        )
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response
