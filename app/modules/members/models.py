from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.shared.ids import new_id


class DeveloperMember(Base):
    __tablename__ = "developer_members"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    developer_id: Mapped[str] = mapped_column(String, ForeignKey("developers.id"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    org_role: Mapped[str] = mapped_column(String(50), nullable=False, default="member")  # owner, admin, member
    invited_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    invited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    joined_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint("developer_id", "user_id", name="uq_developer_member"),)
