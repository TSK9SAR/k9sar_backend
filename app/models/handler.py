# app/models/handler.py
from sqlalchemy import Column, Integer, String, Boolean, Text, func, DateTime, ForeignKey, Numeric, UniqueConstraint, Date
from sqlalchemy.orm import relationship
from app.database import Base

class Handler(Base):
    __tablename__ = "handlers"

    handler_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False, unique=True)

    experience_level = Column(String(50), nullable=True)
    status = Column(String(50), nullable=True)
    group_affiliation = Column(String(200), nullable=True)  
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    # 1–1 User ↔ Handler
    user = relationship("User", back_populates="handler")

    # 1–* Handler ↔ Team
    teams = relationship(
        "Team",
        back_populates="handler",
        cascade="all, delete-orphan",
    )

    affiliation_id = Column(Integer, ForeignKey("affiliations.affiliation_id"), nullable=True, index=True)
    affiliation = relationship("Affiliation")


class Affiliation(Base):
    __tablename__ = "affiliations"

    affiliation_id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False, unique=True)
    callout_line = Column(String(255), nullable=True)

    contact_name = Column(String(120), nullable=True)
    phone = Column(String(50), nullable=True)
    location = Column(String(120), nullable=True)
    url = Column(String(255), nullable=True)

    public_slug = Column(String(80), unique=True, nullable=True)
    allow_public_embed = Column(Boolean, nullable=False, default=False)
    embed_title = Column(String(255), nullable=True)

    sortorder = Column(Integer, nullable=True)
    is_active = Column(Boolean, nullable=False, server_default="1")


class HandlerDues(Base):
    __tablename__ = "handler_dues"

    dues_id = Column(Integer, primary_key=True, index=True)

    handler_id = Column(Integer, ForeignKey("handlers.handler_id"), nullable=False)
    dues_year = Column(Integer, nullable=False)

    amount_due = Column(Numeric(10, 2), nullable=False, default=20.00)
    amount_paid = Column(Numeric(10, 2), nullable=False, default=0.00)

    status = Column(String(20), nullable=False, default="unpaid")  # unpaid | paid | waived
    paid_on = Column(Date, nullable=True)

    payment_method = Column(String(50), nullable=True)
    reference_note = Column(String(255), nullable=True)

    recorded_by_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=True)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("handler_id", "dues_year", name="uq_handler_dues_handler_year"),
    )