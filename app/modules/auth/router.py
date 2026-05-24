from fastapi import APIRouter, Depends, Response, Request, Cookie
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.database import get_db
from app.core.deps import get_current_user
from app.modules.auth import schemas, service
from app.modules.auth.models import User
from app.shared.response import ok

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register/developer")
async def register_developer(
    req: schemas.RegisterDeveloperRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await service.register_developer(db, req)
    tokens = await service.create_tokens(user)
    response_data = {
        "user": schemas.UserResponse.model_validate(user).model_dump(),
        "access_token": tokens["access_token"],
        "token_type": "bearer",
        "expires_in": tokens["expires_in"],
    }
    response = JSONResponse(content=ok(response_data, request=request), status_code=201)
    response.set_cookie(
        key="refresh_token",
        value=tokens["refresh_token"],
        httponly=True,
        secure=False,  # Set True in production
        samesite="lax",
        max_age=14 * 24 * 60 * 60,
    )
    return response


@router.post("/login/developer")
async def login_developer(
    req: schemas.LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await service.authenticate_user(db, req.email, req.password, "developer")
    tokens = await service.create_tokens(user)
    response_data = {
        "user": schemas.UserResponse.model_validate(user).model_dump(),
        "access_token": tokens["access_token"],
        "token_type": "bearer",
        "expires_in": tokens["expires_in"],
    }
    response = JSONResponse(content=ok(response_data, request=request))
    response.set_cookie(
        key="refresh_token",
        value=tokens["refresh_token"],
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=14 * 24 * 60 * 60,
    )
    return response


@router.post("/login/buyer")
async def login_buyer(
    req: schemas.LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await service.authenticate_user(db, req.email, req.password, "buyer")
    tokens = await service.create_tokens(user)
    response_data = {
        "user": schemas.UserResponse.model_validate(user).model_dump(),
        "access_token": tokens["access_token"],
        "token_type": "bearer",
        "expires_in": tokens["expires_in"],
    }
    response = JSONResponse(content=ok(response_data, request=request))
    response.set_cookie(
        key="refresh_token",
        value=tokens["refresh_token"],
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=14 * 24 * 60 * 60,
    )
    return response


@router.post("/login/admin")
async def login_admin(
    req: schemas.LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await service.authenticate_user(db, req.email, req.password, "admin")
    tokens = await service.create_tokens(user)
    response_data = {
        "user": schemas.UserResponse.model_validate(user).model_dump(),
        "access_token": tokens["access_token"],
        "token_type": "bearer",
        "expires_in": tokens["expires_in"],
    }
    response = JSONResponse(content=ok(response_data, request=request))
    response.set_cookie(
        key="refresh_token",
        value=tokens["refresh_token"],
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=14 * 24 * 60 * 60,
    )
    return response


@router.post("/refresh")
async def refresh_token(
    request: Request,
    req: Optional[schemas.RefreshRequest] = None,
    refresh_token: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db),
):
    token = None
    if req and req.refresh_token:
        token = req.refresh_token
    elif refresh_token:
        token = refresh_token

    if not token:
        from app.core.exceptions import UnauthorizedError
        raise UnauthorizedError("No refresh token provided")

    tokens = await service.refresh_access_token(db, token)
    response_data = {
        "access_token": tokens["access_token"],
        "token_type": "bearer",
        "expires_in": tokens["expires_in"],
    }
    response = JSONResponse(content=ok(response_data, request=request))
    response.set_cookie(
        key="refresh_token",
        value=tokens["refresh_token"],
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=14 * 24 * 60 * 60,
    )
    return response


@router.post("/logout")
async def logout(
    request: Request,
    req: Optional[schemas.RefreshRequest] = None,
    refresh_token: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db),
):
    token = None
    if req and req.refresh_token:
        token = req.refresh_token
    elif refresh_token:
        token = refresh_token

    if token:
        await service.logout_user(db, token)

    response = JSONResponse(content=ok({"message": "Logged out successfully"}, request=request))
    response.delete_cookie(key="refresh_token")
    return response


@router.post("/password/reset/request")
async def password_reset_request(
    req: schemas.PasswordResetRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await service.request_password_reset(db, req.email)
    return ok({"message": "If that email exists, you will receive a reset link shortly."}, request=request)


@router.post("/password/reset/confirm")
async def password_reset_confirm(
    req: schemas.PasswordResetConfirm,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await service.confirm_password_reset(db, req.token, req.new_password)
    return ok({"message": "Password has been reset successfully."}, request=request)


@router.get("/me")
async def get_me(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    return ok(schemas.UserResponse.model_validate(current_user).model_dump(), request=request)


@router.post("/register/buyer-by-code", status_code=201)
async def register_buyer_by_code(
    req: schemas.RegisterBuyerByCodeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Self-register as a buyer by entering a public project code (no invitation email required)."""
    from app.modules.buyers.service import register_buyer_by_code as _register
    user = await _register(db, req)
    tokens = await service.create_tokens(user)
    response_data = {
        "user": schemas.UserResponse.model_validate(user).model_dump(),
        "access_token": tokens["access_token"],
        "token_type": "bearer",
        "expires_in": tokens["expires_in"],
    }
    response = JSONResponse(content=ok(response_data, request=request), status_code=201)
    response.set_cookie(
        key="refresh_token",
        value=tokens["refresh_token"],
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=14 * 24 * 60 * 60,
    )
    return response


@router.post("/register/buyer-by-invitation/{token}")
async def register_buyer_by_invitation(
    token: str,
    req: schemas.RegisterBuyerByInvitationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    from app.modules.buyers.service import accept_invitation
    user = await accept_invitation(db, token, req)
    tokens = await service.create_tokens(user)
    response_data = {
        "user": schemas.UserResponse.model_validate(user).model_dump(),
        "access_token": tokens["access_token"],
        "token_type": "bearer",
        "expires_in": tokens["expires_in"],
    }
    response = JSONResponse(content=ok(response_data, request=request), status_code=201)
    response.set_cookie(
        key="refresh_token",
        value=tokens["refresh_token"],
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=14 * 24 * 60 * 60,
    )
    return response
