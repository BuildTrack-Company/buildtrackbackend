from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional

from app.core.database import get_db
from app.modules.public import service
from app.modules.uploads.schemas import UPLOAD_CATEGORIES
from app.shared.response import ok

router = APIRouter(tags=["public"])

# Public, read-only pages change slowly. Let browsers/proxies serve cached
# copies instantly and revalidate in the background.
_PUBLIC_CACHE = "public, max-age=30, stale-while-revalidate=300"


@router.get("/public/directory")
async def get_directory(
    request: Request,
    response: Response,
    area: Optional[str] = None,
    sort: str = "latest",
    db: AsyncSession = Depends(get_db),
):
    cards = await service.get_directory(db, area=area, sort=sort)
    response.headers["Cache-Control"] = _PUBLIC_CACHE
    return ok(cards, request=request)


@router.get("/public/projects/{slug}")
async def get_visibility_page(
    slug: str,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    data = await service.get_visibility_page(db, slug)
    response.headers["Cache-Control"] = _PUBLIC_CACHE
    return ok(data, request=request)


class PageViewRequest(BaseModel):
    session_id: str
    duration_seconds: Optional[int] = None
    referrer: Optional[str] = None


@router.post("/public/projects/{slug}/view", status_code=202)
async def log_visibility_view(
    slug: str,
    req: PageViewRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    country = request.headers.get("cf-ipcountry") or request.headers.get("x-country-code")
    await service.log_view(
        db, slug, req.session_id,
        country_code=country,
        duration_seconds=req.duration_seconds,
        referrer=req.referrer,
    )
    return ok({"status": "recorded"}, request=request)


@router.get("/public/projects/{slug}/photos/{photo_id}")
async def get_visibility_photo(
    slug: str,
    photo_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    url = await service.get_photo_signed_url(db, slug, photo_id)
    return ok({"signed_url": url}, request=request)


@router.get("/upload-categories")
async def list_upload_categories(request: Request):
    return ok(UPLOAD_CATEGORIES, request=request)
