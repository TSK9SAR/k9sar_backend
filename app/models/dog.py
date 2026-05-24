from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base

class Dog(Base):
    __tablename__ = "dogs"

    dog_id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    breed = Column(String(100))
    sex = Column(String(20))
    dob = Column(DateTime)
    photo_url = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # documents = relationship("Document", back_populates="dog")

    teams = relationship(
        "Team",
        back_populates="dog",
        cascade="all, delete-orphan",
    )
