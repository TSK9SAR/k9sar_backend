from sqlalchemy import Table, Column, Integer, ForeignKey
from app.database import Base

# Association table: user_roles(user_id, role_id)
user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.user_id"), primary_key=True),
    Column("role_id", Integer, ForeignKey("roles.role_id"), primary_key=True),
)