from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class VoiceCallPermission(Base):
    __tablename__ = "voice_call_permissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    wa_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    phone_normalized: Mapped[str] = mapped_column(String(20), nullable=False)
    permission_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
