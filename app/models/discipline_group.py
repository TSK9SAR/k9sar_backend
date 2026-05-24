# app/models/discipline_group.py
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from app.database import Base
from app.models.user_discipline_group import user_discipline_groups

class DisciplineGroup(Base):
    __tablename__ = "discipline_groups"

    group_id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True, index=True)
    sortorder = Column(Integer, nullable=False, default=100)
    show_operational = Column(Integer, nullable=False, default=1)  # 1 for visible, 0 for hidden
    show_generic = Column(Integer, nullable=False, default=0)  # 1 for visible, 0 for hidden

    disciplines = relationship("Discipline", back_populates="group", cascade="all,delete")
    evaluators = relationship(
        "User",
        secondary=user_discipline_groups,
        back_populates="discipline_groups",
    )
