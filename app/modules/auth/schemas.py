from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from app.core.security import validate_password_strength


class RegisterDeveloperRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    company_name: str
    phone: Optional[str] = None

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if not validate_password_strength(v):
            raise ValueError("Password must be at least 10 characters with at least 1 digit or special character")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: Optional[str] = None


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v):
        if not validate_password_strength(v):
            raise ValueError("Password must be at least 10 characters with at least 1 digit or special character")
        return v


class UserResponse(BaseModel):
    id: str
    email: str
    role: str
    full_name: Optional[str]
    is_active: bool
    email_verified: bool

    model_config = {"from_attributes": True}


class RegisterBuyerByInvitationRequest(BaseModel):
    full_name: str
    password: str
    phone: Optional[str] = None

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if not validate_password_strength(v):
            raise ValueError("Password must be at least 10 characters with at least 1 digit or special character")
        return v


class RegisterBuyerByCodeRequest(BaseModel):
    project_code: str
    email: EmailStr
    full_name: str
    password: str
    phone: Optional[str] = None
    unit_number: Optional[str] = None

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if not validate_password_strength(v):
            raise ValueError("Password must be at least 10 characters with at least 1 digit or special character")
        return v


class VerifyEmailRequest(BaseModel):
    code: str
