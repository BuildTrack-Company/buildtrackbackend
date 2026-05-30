from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, Integer, Text, Float
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.shared.ids import new_id


class Upload(Base):
    __tablename__ = "uploads"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    developer_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    milestone_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    upload_session_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # ── Construction Update fields (brief Section 7 ConstructionUpdate) ──────
    # In domain language, an Upload IS a Construction Update.
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    progress_at_upload: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 0-100
    capture_latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    capture_longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    accuracy_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    distance_from_site_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # server-validated
    within_boundary: Mapped[bool] = mapped_column(Boolean, default=False)  # server-validated within 100m
    gps_validated: Mapped[bool] = mapped_column(Boolean, default=False)
    photo_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(50), default="pending")  # pending, processing, complete, flagged
    flag_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    notification_fanout_status: Mapped[str] = mapped_column(String(50), default="pending")
    notification_fanout_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class Photo(Base):
    __tablename__ = "photos"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    upload_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    cloudinary_public_id: Mapped[str] = mapped_column(String(500), nullable=False)
    cloudinary_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    original_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    capture_latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    capture_longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    accuracy_m: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exif_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON string
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class UploadSession(Base):
    __tablename__ = "upload_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    developer_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    capture_latitude: Mapped[float] = mapped_column(Float, nullable=False)
    capture_longitude: Mapped[float] = mapped_column(Float, nullable=False)
    accuracy_m: Mapped[float] = mapped_column(Float, nullable=False)
    photo_count: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
