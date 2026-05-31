from datetime import datetime, timezone, date
from typing import Optional
from sqlalchemy import String, DateTime, Integer, Text, Date
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.shared.ids import new_id

SITE_VISIT_STATUSES = ["requested", "confirmed", "rescheduled", "completed", "cancelled", "no_show"]
TIME_SLOTS = ["morning", "afternoon", "evening"]


class SiteVisitRequest(Base):
    """A request from a buyer or prospective buyer to visit a project site."""
    __tablename__ = "site_visit_requests"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    developer_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    requester_user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    phone: Mapped[str] = mapped_column(String(50), nullable=False)
    requested_date: Mapped[date] = mapped_column(Date, nullable=False)
    preferred_time_slot: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    party_size: Mapped[int] = mapped_column(Integer, default=1)
    purpose: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="requested")
    confirmed_datetime: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    developer_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cancellation_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
