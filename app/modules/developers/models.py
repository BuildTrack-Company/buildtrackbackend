from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, Integer, Text, Float
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.shared.ids import new_id


class Developer(Base):
    __tablename__ = "developers"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # ── Credibility profile (brief Section 4.3 / Section 7) ──────────────────
    years_operating: Mapped[int] = mapped_column(Integer, default=0)
    projects_completed: Mapped[int] = mapped_column(Integer, default=0)
    active_developments: Mapped[int] = mapped_column(Integer, default=0)
    avg_update_frequency_days: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    update_consistency_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    company_overview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    subscription_tier: Mapped[str] = mapped_column(String(50), default="trial")
    subscription_status: Mapped[str] = mapped_column(String(50), default="active")
    subscription_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    logo_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    website: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
