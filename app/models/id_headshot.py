# app/models/id_headshot.py

from sqlalchemy import Column, Integer, LargeBinary, String, DateTime, Boolean, ForeignKey
from sqlalchemy.sql import func
from app.database import Base

class HandlerIdHeadshot(Base):
    __tablename__ = "handler_id_headshots"

    headshot_id = Column(Integer, primary_key=True, index=True)
    handler_id = Column(Integer, ForeignKey("handlers.handler_id"), nullable=False, index=True)
    image_png = Column(LargeBinary, nullable=False)
    sha256_hash = Column(String(64), nullable=False)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    uploaded_by_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)


class DogIdHeadshot(Base):
    __tablename__ = "dog_id_headshots"

    headshot_id = Column(Integer, primary_key=True, index=True)
    dog_id = Column(Integer, ForeignKey("dogs.dog_id"), nullable=False, index=True)
    image_png = Column(LargeBinary, nullable=False)
    sha256_hash = Column(String(64), nullable=False)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    uploaded_by_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)