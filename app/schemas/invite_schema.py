from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Literal
from datetime import datetime

class InviteCreate(BaseModel):
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None

    # Optional: assign a role at creation time, or do it later
    role_ids: Optional[list[int]] = None


class InviteCreateIn(BaseModel):
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    role_ids: List[int] = Field(default_factory=list)

class InviteCreateOut(BaseModel):
    user_id: int
    email: EmailStr
    invite_url: str
    expires_at: datetime

class InviteVerifyOut(BaseModel):
    valid: bool
    reason: Optional[str] = None  # "expired", "used", "not_found"
    email: Optional[EmailStr] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class InviteAcceptIn(BaseModel):
    token: str
    username: str
    password: str = Field(min_length=8)


class InviteAcceptOut(BaseModel):
    ok: bool
    user_id: int


class InviteHistoryItem(BaseModel):
    invite_id: int
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: datetime
    expires_at: datetime
    completed_at: Optional[datetime] = None
    status: Literal["pending", "completed", "expired"]
    remaining_seconds: int


class InviteHistoryCounts(BaseModel):
    all: int
    pending: int
    completed: int
    expired: int


class InviteHistoryOut(BaseModel):
    items: List[InviteHistoryItem]
    total: int
    counts: InviteHistoryCounts
    page: int
    page_size: int
    evaluated_at: datetime
