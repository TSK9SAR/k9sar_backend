from pydantic import BaseModel
from datetime import date, datetime
from typing import Optional, List

class CertificateView(BaseModel):
    certification_id: int

    # Who/what is certified
    handler_name: Optional[str] = None
    dog_name: Optional[str] = None
    team_name: Optional[str] = None

    # What standard/discipline
    discipline_name: str
    standard_name: str

    # Dates
    date_awarded: Optional[date] = None
    effective_start: Optional[date] = None
    expires_at: Optional[date] = None

    # Where/issuer
    location: Optional[str] = None
    supervisor_name: Optional[str] = None
    last_actor_name: Optional[str] = None
    validation_id: Optional[str] = None
    seal_short_code: Optional[str] = None

    # ✅ status (needed for print logic)
    status: Optional[str] = None

    evaluation_complete: Optional[bool] = None

    # ✅ dual-evaluator flag
    requires_co_evaluator: Optional[bool] = None

    # Primary signature (already correct)
    supervisor_signature_url: Optional[str] = None
    supervisor_signature_hash: Optional[str] = None
    supervisor_signature_updated_at: Optional[datetime] = None

    # ✅ NEW: co-evaluator fields
    co_evaluator_user_id: Optional[int] = None
    co_evaluator_name: Optional[str] = None
    co_evaluated_at: Optional[datetime] = None

    co_signature_url: Optional[str] = None
    co_signature_hash: Optional[str] = None
    co_signature_updated_at: Optional[datetime] = None

    issued_at: Optional[datetime] = None
    can_view: bool = False


class CertificateSealView(BaseModel):
    certification_id: int
    integrity: str
    standing: str
    seal_hash: str
    short_code: str
    superseded_by_certification_id: Optional[int] = None
    issued_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None

class CertificationHistoryRowOut(BaseModel):
    certification_id: int

    team_id: int
    team_name: Optional[str] = None

    handler_name: Optional[str] = None
    dog_name: Optional[str] = None

    discipline_id: Optional[int] = None
    discipline_name: Optional[str] = None

    standard_id: Optional[int] = None
    standard_name: Optional[str] = None

    status: str

    date_awarded: Optional[str] = None
    effective_start: Optional[str] = None
    expires_at: Optional[str] = None
    issued_at: Optional[str] = None

    location: Optional[str] = None

    supervisor_id: Optional[int] = None
    supervisor_name: Optional[str] = None

    co_evaluator_user_id: Optional[int] = None
    co_evaluator_name: Optional[str] = None
    co_evaluated_at: Optional[str] = None
    co_evaluator_note: Optional[str] = None

    last_actor_user_id: Optional[int] = None
    last_actor_name: Optional[str] = None

    supervisor_signature_updated_at: Optional[str] = None
    co_signature_updated_at: Optional[str] = None

    comment: Optional[str] = None


class CertificationHistoryOut(BaseModel):
    selected_certification_id: int
    lineage_key: str

    team_id: int
    team_name: Optional[str] = None
    handler_name: Optional[str] = None
    dog_name: Optional[str] = None

    discipline_id: Optional[int] = None
    discipline_name: Optional[str] = None

    rows: List[CertificationHistoryRowOut]
