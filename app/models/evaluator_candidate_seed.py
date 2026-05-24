# from sqlalchemy import Column, Integer, Boolean, String, DateTime, ForeignKey
# from sqlalchemy.sql import func
# from sqlalchemy.orm import relationship

# from app.database import Base

# class EvaluatorCandidateSeed(Base):
#     __tablename__ = "evaluator_candidate_seed"

#     user_id = Column(Integer, ForeignKey("users.user_id"), primary_key=True)
#     group_id = Column(Integer, ForeignKey("discipline_groups.group_id"), primary_key=True)

#     source = Column(String(40), default="legacy_reconstructed")
#     notes = Column(String(255), nullable=True)

#     is_active = Column(Boolean, default=True)

#     created_at = Column(DateTime, server_default=func.now())

#     # optional relationships (not required but nice)
#     user = relationship("User")
#     group = relationship("DisciplineGroup")