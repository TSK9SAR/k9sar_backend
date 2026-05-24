from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field


class HandlerSummary(BaseModel):
    handler_id: int
    status: Optional[str] = None

    class Config:
        from_attributes = True


class AdminUserOut(BaseModel):
    user_id: int
    first_name: str
    last_name: str
    email: EmailStr
    username: str
    phone: Optional[str] = None

    roles: List[str] = Field(default_factory=list)      # role_name strings
    role_ids: List[int] = Field(default_factory=list)

    handler: Optional[HandlerSummary] = None

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_active: bool = True
    
    class Config:
        from_attributes = True


class AdminUserListOut(BaseModel):
    items: List[AdminUserOut]
    total: int


class AdminUserPatch(BaseModel):
    # roles only on user patch (handler status is handled by /admin/handlers)
    role_ids: Optional[List[int]] = None
    is_active: Optional[bool] = None
    email: Optional[EmailStr] = None

class AdminAuthEventOut(BaseModel):
    auth_event_id: int
    user_id: int
    event_type: str
    occurred_at: datetime | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    success: bool = True
    detail: str | None = None

    class Config:
        from_attributes = True

class AdminUserLoginActivityOut(BaseModel):
    user_id: int
    first_name: str
    last_name: str
    email: str | None = None

    last_login_at: datetime | None = None
    login_count: int = 0

    last_mfa_verified_at: datetime | None = None
    mfa_verify_count: int = 0

    last_seen_at: datetime | None = None
    active_now: bool = False

    class Config:
        from_attributes = True 