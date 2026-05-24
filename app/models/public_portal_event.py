from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func

from app.database import Base  # adjust if your Base import is different


class PublicPortalEvent(Base):
    __tablename__ = "public_portal_events"

    event_id = Column(Integer, primary_key=True, autoincrement=True)

    # Store in UTC, timezone-aware
    occurred_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    # Session tracking (frontend-generated)
    session_id = Column(String(64), nullable=True, index=True)

    # Which part of portal triggered it (directory, standards, etc.)
    section = Column(String(50), nullable=False, index=True)

    # Request metadata
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(Text, nullable=True)

    # Referrer URLs can be long → use Text (NOT String(64))
    referer = Column(Text, nullable=True)