from typing import Any, Optional, List
from fastapi import Request


def ok(data: Any, meta: Optional[dict] = None, request: Optional[Any] = None) -> dict:
    """Standard success response envelope."""
    base_meta = {"version": "1.0.0"}
    if request and hasattr(request.state, "request_id"):
        base_meta["request_id"] = request.state.request_id
    if meta:
        base_meta.update(meta)
    return {"data": data, "meta": base_meta}


def paginated(
    items: List[Any],
    total: int,
    page: int,
    limit: int,
    request: Optional[Any] = None,
) -> dict:
    """Paginated response envelope."""
    base_meta = {
        "version": "1.0.0",
        "pagination": {
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit if limit > 0 else 0,
        },
    }
    if request and hasattr(request.state, "request_id"):
        base_meta["request_id"] = request.state.request_id
    return {"data": items, "meta": base_meta}
