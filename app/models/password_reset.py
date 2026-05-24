from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Integer, ForeignKey, String
from sqlalchemy.sql import text
from app.database import Base

class PasswordReset(Base):
    __tablename__ = "password_resets"

    reset_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    token_hash = Column(String(64), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),        # Python side
        server_default=text("CURRENT_TIMESTAMP"),          # DB side (optional but good)
    )
