from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, Integer, Text, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.shared.ids import new_id


class Milestone(Base):
    __tablename__ = "milestones"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending")  # pending, in_progress, complete, delayed
    expected_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    delay_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    delay_new_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expected_date_set_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    workflow_stage_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("workflow_stages.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class MilestoneApproval(Base):
    __tablename__ = "milestone_approvals"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    milestone_id: Mapped[str] = mapped_column(String, ForeignKey("milestones.id", ondelete="CASCADE"), nullable=False, index=True)
    buyer_user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)  # approved | rejected
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
