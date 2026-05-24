from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean    
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
from app.models.discipline_group import DisciplineGroup  # ensures class is registered
from app.models.user_discipline_group import user_discipline_groups
from sqlalchemy import Boolean, ForeignKey, String, Text, DateTime


class User(Base):
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    phone = Column(String(20))
    domicile_lat = Column(Float)
    domicile_lng = Column(Float)
    address_line1 = Column(String(255))
    address_line2 = Column(String(255))
    city = Column(String(100))
    state_province = Column(String(100))
    postal_code = Column(String(20))
    country = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    twofa_enabled = Column(Boolean, nullable=False, default=False)
    twofa_confirmed = Column(Boolean, nullable=False, default=False)
    twofa_secret = Column(String(64), nullable=True)
    twofa_verified_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    # inside class User(Base):
    signature_url = Column(String(255), nullable=True)
    signature_hash = Column(String(64), nullable=True)
    signature_updated_at = Column(DateTime, nullable=True)
    last_login_at = Column(DateTime, nullable=True)
    last_mfa_verified_at = Column(DateTime, nullable=True)

    login_count = Column(Integer, nullable=False, default=0)
    mfa_verify_count = Column(Integer, nullable=False, default=0)

    last_seen_at = Column(DateTime, nullable=True)

    handler = relationship(
        "Handler",
        back_populates="user",
        uselist=False,   # 1–1
    )

    roles = relationship(
        "Role",
        secondary="user_roles",
        back_populates="users",
    )

    discipline_groups = relationship(
        "DisciplineGroup",
        secondary=user_discipline_groups,
        back_populates="evaluators",
    )


def is_evaluator(user: User) -> bool:
    return bool(getattr(user, "discipline_groups", None)) and len(user.discipline_groups) > 0


class AuthEvent(Base):
    __tablename__ = "auth_events"

    auth_event_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False, index=True)

    event_type = Column(String(32), nullable=False, index=True)  # login, mfa_verify
    occurred_at = Column(DateTime, nullable=False, server_default=func.now())

    ip_address = Column(String(64), nullable=True)
    user_agent = Column(Text, nullable=True)
    success = Column(Boolean, nullable=False, default=True)
    detail = Column(Text, nullable=True)

    user = relationship("User")
