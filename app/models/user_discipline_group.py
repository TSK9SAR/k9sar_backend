# app/models/user_discipline_group.py (or in models/__init__.py)
from sqlalchemy import Table, Column, Integer, ForeignKey
from app.database import Base

user_discipline_groups = Table(
    "user_discipline_groups",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", Integer, ForeignKey("discipline_groups.group_id", ondelete="CASCADE"), primary_key=True),
)

