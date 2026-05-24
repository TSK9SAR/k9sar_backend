# app/models/discipline.py
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base

class Discipline(Base):
    __tablename__ = "disciplines"

    discipline_id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(String(100), nullable=True)
    sortorder = Column(Integer, nullable=False, default=0)
    show_operational = Column(Integer, nullable=False, default=1)  # 1 for visible, 0 for hidden
    show_generic = Column(Integer, nullable=False, default=0)  # 1 for visible, 0 for hidden

    # One discipline → many certifications

    # One discipline → many standards
    standards = relationship(
        "Standard",
        back_populates="discipline",
        cascade="all, delete-orphan",)

    group_id = Column(Integer, ForeignKey("discipline_groups.group_id"), nullable=False)  # or nullable=True
    group = relationship("DisciplineGroup", back_populates="disciplines")

