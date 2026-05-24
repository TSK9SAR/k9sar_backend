from sqlalchemy import BigInteger, Column, Enum, Integer, Date, DateTime, func, Text, ForeignKey, String, Boolean, text
from sqlalchemy.orm import relationship
from app.database import Base

class Certification(Base):
    __tablename__ = "certifications"

    certification_id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.team_id"), nullable=False)
    standard_id = Column(Integer, ForeignKey("standards.standard_id"), nullable=False)

    date_awarded = Column(Date, nullable=False)
    expires_at = Column(Date, nullable=False)

    status = Column(
        Enum("active", "expired", "revoked", "pending", "incomplete", "suspended", "rejected", "expiring", "none", name="certification_status"),
        nullable=False,
        default="active",
    )

    location = Column(String(200))
    comment = Column(String(500))
    document_url = Column(String(200))

    supervisor_id = Column(Integer, nullable=False)
    requires_co_evaluator = Column(Boolean, nullable=False, default=False)
    evaluation_complete = Column(Boolean, nullable=False, default=True)

    co_evaluator_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=True)
    co_evaluated_at = Column(DateTime, nullable=True)
    co_evaluator_note = Column(String(500), nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )
    issued_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    issuer_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=True)
    last_actor_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=True)

    seal_hash = Column(String(64))
    seal_version = Column(Integer, nullable=False, default=1)
    revoked_at = Column(DateTime, nullable=True)

    signature_url = Column(String(255), nullable=True)
    signature_hash = Column(String(64), nullable=True)
    signature_updated_at = Column(DateTime, nullable=True)

    co_signature_url = Column(String(255), nullable=True)
    co_signature_hash = Column(String(64), nullable=True)
    co_signature_updated_at = Column(DateTime, nullable=True)

    team = relationship("Team", back_populates="certifications")
    standard = relationship("Standard", back_populates="certifications")
    last_actor = relationship("User", foreign_keys=[last_actor_user_id])


class CertificationEvent(Base):
    __tablename__ = "certification_events"

    event_id = Column(BigInteger, primary_key=True, autoincrement=True)
    certification_id = Column(Integer, ForeignKey("certifications.certification_id"), nullable=False, index=True)

    event_type = Column(String(50), nullable=False, index=True)

    previous_status = Column(String(20), nullable=True)
    new_status = Column(String(20), nullable=True)

    evaluation_complete_before = Column(Boolean, nullable=True)
    evaluation_complete_after = Column(Boolean, nullable=True)

    requires_co_evaluator_before = Column(Boolean, nullable=True)
    requires_co_evaluator_after = Column(Boolean, nullable=True)
    
    location_before = Column(String(200), nullable=True)
    location_after = Column(String(200), nullable=True)
    comment_before = Column(String(500), nullable=True)
    comment_after = Column(String(500), nullable=True)
    date_awarded_before = Column(Date, nullable=True)
    date_awarded_after = Column(Date, nullable=True)
    expires_at_before = Column(Date, nullable=True)
    expires_at_after = Column(Date, nullable=True)

    actor_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False, index=True)
    note = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, server_default=func.now())