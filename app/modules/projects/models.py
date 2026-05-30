from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, Integer, Text, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.shared.ids import new_id


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    developer_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    project_code: Mapped[str] = mapped_column(String(10), unique=True, nullable=False, index=True)
    slug: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True, index=True)  # public visibility-page URL
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
    # ── Visibility page (brief Section 4.3 / Section 7) ──────────────────────
    visibility_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    visibility_tagline: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    starting_price: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    construction_progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    health_status: Mapped[str] = mapped_column(String(50), default="on_schedule")  # on_schedule, minor_delay, under_review
    activity_overdue_threshold_days: Mapped[int] = mapped_column(Integer, default=14)
    visibility_page_views: Mapped[int] = mapped_column(Integer, default=0)
    visibility_page_published: Mapped[bool] = mapped_column(Boolean, default=False)
    project_type_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("project_types.id"), nullable=True)
    workflow_template_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("workflow_templates.id"), nullable=True)
    current_stage_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("workflow_stages.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
