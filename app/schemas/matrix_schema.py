# app/schemas/matrix_schema.py
from datetime import date, datetime
from typing import Dict, List, Optional
from pydantic import BaseModel
from enum import Enum


class CertStatus(str, Enum):
    active = "active"
    expired = "expired"
    revoked = "revoked"
    pending = "pending"
    incomplete = "incomplete"
    suspended = "suspended"
    expiring = "expiring"
    rejected = "rejected"
    none = "none"


class MatrixCell(BaseModel):
    expires: Optional[date]
    status: CertStatus
    standard_id: int | None = None

    # existing action/display fields
    certification_id: Optional[int] = None
    date_awarded: Optional[date] = None
    supervisor_id: Optional[int] = None
    last_actor_user_id: Optional[int] = None
    supervisor_name: Optional[str] = None

    # add these if the frontend uses them
    location: Optional[str] = None
    comment: Optional[str] = None

    # frontend capability flags
    can_view: bool = False
    can_revoke: bool = False
    can_suspend: bool = False
    can_unsuspend: bool = False
    is_owner: bool = False

    evaluation_complete: bool = True
    requires_co_evaluator: bool = False
    can_co_evaluate: bool = False
    co_evaluator_user_id: int | None = None
    co_evaluator_name: str | None = None
    co_evaluated_at: datetime | None = None
    co_evaluator_note: str | None = None

class MatrixTeam(BaseModel):
    team_id: int
    handler_first: str
    handler_last: str
    dog_name: str
    certifications: Dict[str, MatrixCell]


class CertificationRenew(BaseModel):
    expires_at: Optional[date] = None
    date_awarded: Optional[date] = None
    status: Optional[CertStatus] = CertStatus.active
    document_url: Optional[str] = None


class CertificationMatrixDto(BaseModel):
    disciplines: List[str]
    teams: List[MatrixTeam]