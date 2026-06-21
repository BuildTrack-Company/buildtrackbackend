from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.shared.ids import new_id


class NotificationLog(Base):
    __tablename__ = "notification_log"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    upload_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    buyer_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    developer_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)  # email, sms, whatsapp
    recipient_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    subject: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    template_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="sent")  # sent, failed, delivered, bounced
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    provider_message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Notification(Base):
    """In-app notification shown in the bell feed on each portal."""

    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False, default="info")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    link: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
