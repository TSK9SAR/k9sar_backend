from sqlalchemy import Column, Integer, String, ForeignKey, Table
from sqlalchemy.orm import relationship
from app.database import Base

class Role(Base):
    __tablename__ = "roles"

    role_id = Column(Integer, primary_key=True, index=True)
    role_name = Column(String(50), unique=True, index=True)
    # ... any other fields ...

    users = relationship(
        "User",
        secondary="user_roles",  # same association table
        back_populates="roles",  # must match User.roles
    )
