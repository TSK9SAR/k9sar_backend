from __future__ import annotations
from pydantic import BaseModel
from typing import Optional

from datetime import datetime
from sqlalchemy import (
    Column, Integer, DateTime, Text, Enum, ForeignKey, Index, String
)
from sqlalchemy.orm import relationship

from app.database import Base  # adjust to your Base import


class HandlerAffiliation(Base):
    __tablename__ = "handler_affiliations"

    handler_affiliation_id = Column(Integer, primary_key=True, autoincrement=True)

    handler_id = Column(Integer, ForeignKey("handlers.handler_id", ondelete="CASCADE"), nullable=False)
    affiliation_id = Column(Integer, ForeignKey("affiliations.affiliation_id", ondelete="CASCADE"), nullable=False)

    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_by_user_id = Column(Integer, ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)

    ended_at = Column(DateTime, nullable=True)
    ended_by_user_id = Column(Integer, ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)

    note = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships (optional but handy)
    handler = relationship("Handler", backref="affiliation_memberships")
    affiliation = relationship("Affiliation")
    started_by = relationship("User", foreign_keys=[started_by_user_id])
    ended_by = relationship("User", foreign_keys=[ended_by_user_id])

    __table_args__ = (
        Index("idx_ha_handler", "handler_id"),
        Index("idx_ha_affiliation", "affiliation_id"),
        Index("idx_ha_active", "handler_id", "affiliation_id", "ended_at"),
    )


class AffiliationChangeRequest(Base):
    __tablename__ = "affiliation_change_requests"

    request_id = Column(Integer, primary_key=True, autoincrement=True)

    handler_id = Column(Integer, ForeignKey("handlers.handler_id", ondelete="CASCADE"), nullable=False)
    affiliation_id = Column(Integer, ForeignKey("affiliations.affiliation_id", ondelete="CASCADE"), nullable=False)

    action = Column(Enum("add", "remove", name="affiliation_change_action"), nullable=False)
    status = Column(Enum("pending", "approved", "rejected", name="affiliation_change_status"),
                    nullable=False, default="pending")

    requested_by_user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    requested_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    request_note = Column(Text, nullable=True)

    reviewed_by_user_id = Column(Integer, ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_note = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    handler = relationship("Handler")
    affiliation = relationship("Affiliation")
    requested_by = relationship("User", foreign_keys=[requested_by_user_id])
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_user_id])

    __table_args__ = (
        Index("idx_acr_status_requested_at", "status", "requested_at"),
        Index("idx_acr_handler", "handler_id"),
        Index("idx_acr_affiliation", "affiliation_id"),
        Index("idx_acr_requested_by", "requested_by_user_id"),
    )

class ReviewNoteIn(BaseModel):
    review_note: Optional[str] = None