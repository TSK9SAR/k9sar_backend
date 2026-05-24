# app/schemas/team_schema.py
from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime

TeamStatus = Literal["active", "suspended", "retired", "inactive"]


class TeamBase(BaseModel):
    dog_id: int
    handler_id: int
    status: Optional[str] = "active"

class TeamCreate(BaseModel):
    dog_id: int
    status: Optional[TeamStatus] = "active"
    # handler_id: Optional[int] = None  # optional for backward compat

class TeamUpdate(BaseModel):
    status: Optional[str]

class TeamOut(TeamBase):
    team_id: int

    class Config:
        from_attributes = True
