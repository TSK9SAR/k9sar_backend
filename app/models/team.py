# app/models/team.py
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base

class Team(Base):
    __tablename__ = "teams"

    team_id = Column(Integer, primary_key=True, index=True)
    handler_id = Column(Integer, ForeignKey("handlers.handler_id"), nullable=False)
    dog_id = Column(Integer, ForeignKey("dogs.dog_id"), nullable=False)

    # optional fields (status, call sign, etc.)
    status = Column(String(50), nullable=True)

    certifications = relationship(
        "Certification",
        back_populates="team",
        cascade="all, delete-orphan",
    )

    # documents = relationship("Document", back_populates="team")

    # 👇 This is what the error says is missing
    handler = relationship(
        "Handler",
        back_populates="teams",
    )

    # Dog relationship (similar pattern)
    dog = relationship(
        "Dog",
        back_populates="teams",
   )

