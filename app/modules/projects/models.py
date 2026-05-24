from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, Integer, Text, Float
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.shared.ids import new_id


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    developer_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    project_code: Mapped[str] = mapped_column(String(10), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    location_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    site_latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    site_longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gps_radius_metres: Mapped[float] = mapped_column(Float, default=100.0)
    total_units: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="planning")  # planning, construction, completed
    cover_image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    estimated_completion: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
