from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str
    DATABASE_DIRECT_URL: str
    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    INTERNAL_CRON_TOKEN: str = "change-me"
    ENVIRONMENT: str = "development"
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""
    CLOUDINARY_UPLOAD_PRESET: str = "buildtrack_signed"
    CLOUDINARY_FOLDER_ROOT: str = "buildtrack/dev"
    RESEND_API_KEY: str = ""
    EMAIL_FROM_ADDRESS: str = "onboarding@resend.dev"
    EMAIL_FROM_NAME: str = "BuildTrack"
    EMAIL_REPLY_TO: str = "support@buildtrack.co.ke"
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:5173",
        "http://localhost:8000",  # Swagger UI
        "http://127.0.0.1:8000",
    ]


settings = Settings()
