from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class AdminHandlerOut(BaseModel):
    handler_id: int
    user_id: int

    experience_level: Optional[str] = None
    status: Optional[str] = None
    group_affiliation: Optional[str] = None
    notes: Optional[str] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # small user info for display
    username: Optional[str] = None
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None

    class Config:
        from_attributes = True


class AdminHandlerListOut(BaseModel):
    items: list[AdminHandlerOut]
    total: int


class AdminHandlerPatch(BaseModel):
    status: Optional[str] = Field(default=None, description="active|suspended|inactive")
    experience_level: Optional[str] = None
    group_affiliation: Optional[str] = None
    notes: Optional[str] = None
