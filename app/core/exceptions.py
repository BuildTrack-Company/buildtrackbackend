from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from typing import Optional


class BuildTrackError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400, details: Optional[dict] = None):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class NotFoundError(BuildTrackError):
    def __init__(self, message: str = "Resource not found", details: Optional[dict] = None):
        super().__init__("NOT_FOUND", message, 404, details)


class ForbiddenError(BuildTrackError):
    def __init__(self, message: str = "Access forbidden", details: Optional[dict] = None):
        super().__init__("FORBIDDEN", message, 403, details)


class UnauthorizedError(BuildTrackError):
    def __init__(self, message: str = "Unauthorized", details: Optional[dict] = None):
        super().__init__("UNAUTHORIZED", message, 401, details)


class QuotaExceededError(BuildTrackError):
    def __init__(self, message: str = "Quota exceeded", details: Optional[dict] = None):
        super().__init__("QUOTA_EXCEEDED", message, 429, details)


class GPSRejectedError(BuildTrackError):
    def __init__(self, message: str = "GPS validation failed", details: Optional[dict] = None):
        super().__init__("GPS_REJECTED", message, 422, details)


class DuplicateError(BuildTrackError):
    def __init__(self, message: str = "Resource already exists", details: Optional[dict] = None):
        super().__init__("DUPLICATE", message, 409, details)


class ValidationError(BuildTrackError):
    def __init__(self, message: str = "Validation failed", details: Optional[dict] = None):
        super().__init__("VALIDATION_ERROR", message, 422, details)


def add_exception_handlers(app: FastAPI):
    @app.exception_handler(BuildTrackError)
    async def buildtrack_error_handler(request: Request, exc: BuildTrackError):
        request_id = getattr(request.state, "request_id", "unknown")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                },
                "meta": {
                    "request_id": request_id,
                    "version": "1.0.0",
                },
            },
        )

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        request_id = getattr(request.state, "request_id", "unknown")
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "The requested resource was not found",
                    "details": {},
                },
                "meta": {
                    "request_id": request_id,
                    "version": "1.0.0",
                },
            },
        )

    @app.exception_handler(500)
    async def internal_error_handler(request: Request, exc):
        request_id = getattr(request.state, "request_id", "unknown")
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An internal server error occurred",
                    "details": {},
                },
                "meta": {
                    "request_id": request_id,
                    "version": "1.0.0",
                },
            },
        )
