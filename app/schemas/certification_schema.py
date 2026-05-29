from enum import Enum
from datetime import date, datetime
from typing import Optional, Any, Literal
from pydantic import BaseModel, field_validator

def parse_date_flexible(v: Any) -> Optional[date]:
    if v is None or v == "":
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()

    s = str(v).strip()

    # Fast path: ISO
    try:
        return date.fromisoformat(s)  # YYYY-MM-DD
    except ValueError:
        pass

    fmts = [
        "%m/%d/%Y", "%m/%d/%y",
        "%d/%m/%Y", "%d/%m/%y",
        "%m-%d-%Y", "%d-%m-%Y",
        "%d.%m.%Y",
        "%b %d %Y", "%B %d %Y",
        "%d %b %Y", "%d %B %Y",
    ]
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue

    raise ValueError("Invalid date. Use YYYY-MM-DD or a common format like MM/DD/YYYY.")


class CertStatus(str, Enum):
    active = "active"
    expired = "expired"
    revoked = "revoked"
    pending = "pending"
    incomplete = "incomplete"
    suspended = "suspended"
    rejected = "rejected"
    expiring = "expiring"
    none = "none"   


class CertificationBase(BaseModel):
    team_id: int
    standard_id: int
    date_awarded: date
    expires_at: date
    status: CertStatus = CertStatus.active
    location: Optional[str] = None
    comment: Optional[str] = None
    document_url: Optional[str] = None
    incomplete_days: Optional[int] = None  # days the incomplete status remains.
    effective_days: Optional[int] = None  # days the certification is effective after the date

class CertificationCreate(CertificationBase):
    team_id: int
    standard_id: int
    date_awarded: date
    expires_at: date
    status: CertStatus = CertStatus.active
    document_url: Optional[str] = None
    location: Optional[str] = None
    comment: Optional[str] = None
    supervisor_id: Optional[int] = None
    requires_co_evaluator: bool = False
    evaluation_complete: Optional[bool] = None
    incomplete_days: Optional[int] = None  # days the incomplete status remains.
    effective_days: Optional[int] = None  # days the certification is effective after the date


    @field_validator("date_awarded", mode="before")
    @classmethod
    def _parse_date_awarded(cls, v):
        return parse_date_flexible(v)

class CertificationUpdate(BaseModel):
    """
    Used for PATCH updates to an existing certification.
    All fields optional.
    """
    date_awarded: Optional[date] = None
    expires_at: Optional[date] = None
    status: Optional[CertStatus] = None
    document_url: Optional[str] = None
    location: Optional[str] = None
    comment: Optional[str] = None
    supervisor_id: Optional[int] = None
    requires_co_evaluator: bool = False
    evaluation_complete: Optional[bool] = None
    evaluation_complete: Optional[bool] = None

    @field_validator("date_awarded", mode="before")
    @classmethod
    def _parse_date_awarded(cls, v):
        return parse_date_flexible(v)

class CertificationOut(CertificationBase):
    team_id: int
    certification_id: int
    standard_id: int
    supervisor_id: int
    created_at: datetime
    updated_at: datetime
    incomplete_days: Optional[int] = None  # days the incomplete status remains.
    effective_days: Optional[int] = None  # days the certification is effective after the date

    signature_url: Optional[str] = None
    signature_hash: Optional[str] = None
    signature_updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

class CertificationRevoke(BaseModel):
    status: Literal["revoked"] = "revoked"

class CoEvaluateIn(BaseModel):
    action: Literal["approve", "reject"]
    note: str | None = None

    class Config:
        orm_mode = True

class CertificationCorrectionIn(BaseModel):
    location: str | None = None
    comment: str | None = None
    date_awarded: date | None = None
    expires_at: date | None = None
    requires_co_evaluator: bool = False
    evaluation_complete: Optional[bool] = None
    reason: str | None = None   # optional, but useful for audit

class CertificationEventOut(BaseModel):
    event_id: int
    certification_id: int
    event_type: str

    previous_status: Optional[str] = None
    new_status: Optional[str] = None

    evaluation_complete_before: Optional[bool] = None
    evaluation_complete_after: Optional[bool] = None

    requires_co_evaluator_before: Optional[bool] = None
    requires_co_evaluator_after: Optional[bool] = None

    incomplete_days_before: Optional[int] = None
    incomplete_days_after: Optional[int] = None

    effective_days_before: Optional[int] = None
    effective_days_after: Optional[int] = None

    actor_user_id: int
    actor_name: Optional[str] = None

    location_before: Optional[str] = None
    location_after: Optional[str] = None
    comment_before: Optional[str] = None
    comment_after: Optional[str] = None
    date_awarded_before: Optional[date] = None
    date_awarded_after: Optional[date] = None
    expires_at_before: Optional[date] = None
    expires_at_after: Optional[date] = None

    note: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True