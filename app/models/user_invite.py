from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base


def utcnow_naive() -> datetime:
    # UTC time but tz-naive (best with MySQL DATETIME)
    return datetime.now(timezone.utc).replace(tzinfo=None)


class UserInvite(Base):
    __tablename__ = "user_invites"

    invite_id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # Invite may be for not-yet-created user
    user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=True, index=True)

    email = Column(String(255), nullable=False, index=True)
    first_name = Column(String(80), nullable=True)
    last_name = Column(String(80), nullable=True)
    phone = Column(String(40), nullable=True)

    # Store roles as JSON text for now (can migrate to join table later)
    role_ids_json = Column(Text, nullable=True)

    token_hash = Column(String(64), unique=True, nullable=False, index=True)

    expires_at = Column(DateTime, nullable=False)   # UTC-naive
    used_at = Column(DateTime, nullable=True)       # UTC-naive

    created_at = Column(
        DateTime,
        nullable=False,
        default=utcnow_naive,       # Python-side default (UTC-naive)
        server_default=func.now(),  # DB-side default (optional)
    )

    created_by_user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=True, index=True)

    # ---- Convenience helpers ----
    def get_role_ids(self) -> List[int]:
        if not self.role_ids_json:
            return []
        try:
            val = json.loads(self.role_ids_json)
            return [int(x) for x in (val or [])]
        except Exception:
            return []

    def set_role_ids(self, role_ids: List[int]) -> None:
        cleaned = [int(x) for x in (role_ids or [])]
        self.role_ids_json = json.dumps(cleaned)
