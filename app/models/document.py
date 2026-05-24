# app/models/document.py
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.sql import func
from app.database import Base
from sqlalchemy.orm import relationship

class Document(Base):
    __tablename__ = "documents"

    document_id = Column(Integer, primary_key=True, autoincrement=True)

    original_filename = Column(String(255), nullable=False)
    stored_filename = Column(String(255), nullable=False, unique=True, index=True)
    content_type = Column(String(100), nullable=True)
    size_bytes = Column(Integer, nullable=False)

    created_by_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Optional attachments (plain IDs for now)
    standard_id = Column(Integer, ForeignKey("standards.standard_id"), nullable=True)
    team_id = Column(Integer, ForeignKey("teams.team_id"), nullable=True)
    dog_id = Column(Integer, ForeignKey("dogs.dog_id"), nullable=True)

    standard = relationship("Standard", back_populates="documents")
    team = relationship("Team", back_populates="documents")
    dog = relationship("Dog", back_populates="documents")
 

class DocumentOut(BaseModel):
    document_id: int
    original_filename: str
    download_url: str

    class Config:
        from_attributes = True
