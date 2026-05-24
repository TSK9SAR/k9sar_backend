from __future__ import annotations
import logging
from datetime import datetime, date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, aliased
from sqlalchemy import case

from app.database import get_db
from app.models import Certification, Team, Handler, Dog, Standard, Discipline, User
from app.models.certification import CertificationEvent
from app.schemas.certificate_schema import CertificateView, CertificationHistoryOut, CertificationHistoryRowOut
from app.schemas.certification_schema import (
    CertificationCreate,
    CertificationUpdate,
    CertificationOut,
    CertificationRevoke,
    CoEvaluateIn,
    CertificationEventOut,
    CertificationCorrectionIn,
)

from app.services.matrix_service import _normalize_status, build_certification_matrix
from app.utils.auth import get_current_user, can_view_certificate, require_mfa_verified
from app.utils.authz import (
    require_evaluator_for_standard,
    require_evaluator_for_cert,
    forbid_self_certification,
)
from app.utils.seal import compute_seal_hash, short_code
from app.utils.auth import user_has_role

router = APIRouter(prefix="/certifications", tags=["certifications"])


def _full_name(u: Optional[User]) -> Optional[str]:
    if not u:
        return None
    first = (getattr(u, "first_name", "") or "").strip()
    last = (getattr(u, "last_name", "") or "").strip()
    full = f"{first} {last}".strip()
    return full or None

def log_cert_event(
    db: Session,
    *,
    cert: Certification,
    event_type: str,
    actor_user_id: int,
    previous_status: str | None,
    new_status: str | None,
    evaluation_complete_before: bool | None,
    evaluation_complete_after: bool | None,
    requires_co_evaluator_before: bool | None,
    requires_co_evaluator_after: bool | None,
    location_before: str | None = None,
    location_after: str | None = None,
    comment_before: str | None = None,
    comment_after: str | None = None,
    date_awarded_before: date | None = None,
    date_awarded_after: date | None = None,
    expires_at_before: date | None = None,
    expires_at_after: date | None = None,
    note: str | None = None,
) -> None:
    db.add(
        CertificationEvent(
            certification_id=cert.certification_id,
            event_type=event_type,
            previous_status=previous_status,
            new_status=new_status,
            evaluation_complete_before=evaluation_complete_before,
            evaluation_complete_after=evaluation_complete_after,
            requires_co_evaluator_before=requires_co_evaluator_before,
            requires_co_evaluator_after=requires_co_evaluator_after,
            actor_user_id=actor_user_id,
            location_before=location_before,
            location_after=location_after,
            comment_before=comment_before,
            comment_after=comment_after,
            date_awarded_before=date_awarded_before,
            date_awarded_after=date_awarded_after,
            expires_at_before=expires_at_before,
            expires_at_after=expires_at_after,
            note=note,
        )
    )

def _determine_status(cert: Certification) -> str:
    """
    Decide the matrix status label for a certification.

    Rules:
      1. Preserve explicit workflow/business statuses from the DB.
      2. Only decorate ACTIVE with expiring/expired based on expires_at.
      3. Never convert INCOMPLETE into ACTIVE.
    """
    today = date.today()

    raw_status = getattr(cert, "status", None)
    s = _normalize_status(raw_status)

    # revoked always wins
    if s.startswith("revok"):
        return "revoked"

    # preserve explicit DB statuses
    if s in {"pending", "incomplete", "suspended", "rejected"}:
        return s

    # only decorate active-like statuses by expiration
    if s in {"active", "expired", ""}:
        expires = getattr(cert, "expires_at", None)
        if expires:
            exp_date = expires.date() if hasattr(expires, "date") else expires
            if exp_date <= today:
                return "expired"
            days = (exp_date - today).days
            if days <= 60:
                return "expiring"
            return "active"
        return "active"

    # fallback: preserve unknown statuses rather than lying
    return s or "active"

def standing_for(cert: Certification) -> str:
    # tweak to your rules
    if getattr(cert, "revoked_at", None):
        return "REVOKED"

    exp = getattr(cert, "expires_at", None)
    if exp:
        exp_date = exp.date() if hasattr(exp, "date") else exp
        if exp_date < date.today():
            return "EXPIRED"
        
    return (getattr(cert, "status", None) or "ACTIVE").upper()

def cert_owner_user_id(cert) -> int | None:
    """
    Returns the user_id of the certification owner.
    """
    if cert.team and cert.team.handler and cert.team.handler.user_id:
        return cert.team.handler.user_id

    if getattr(cert, "owner_user_id", None):
        return cert.owner_user_id

    return None


def can_owner_or_admin_manage_cert(current_user, cert) -> bool:
    """
    Owner or admin may manage certification (revoke/suspend/etc.)
    """
    if user_has_role(current_user, "admin"):
        return True

    owner_id = cert_owner_user_id(cert)
    current_user_id = getattr(current_user, "user_id", None) or getattr(current_user, "id", None)

    if owner_id is not None and current_user_id is not None and int(owner_id) == int(current_user_id):
        return True

    return False


def require_owner_or_admin(current_user, cert):
    if can_owner_or_admin_manage_cert(current_user, cert):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not authorized to manage this certification",
    )

def compute_default_expiration(*, date_awarded, evaluation_complete: bool, standard) -> object:
    if not date_awarded:
        return None

    if evaluation_complete:
        effective_days = int(getattr(standard, "effective_days", 0) or 0)
        if effective_days <= 0:
            raise HTTPException(
                status_code=400,
                detail="Selected standard is missing a valid effective_days value.",
            )
        return date_awarded + timedelta(days=effective_days)

    incomplete_days = int(getattr(standard, "incomplete_days", 0) or 0)
    if incomplete_days <= 0:
        raise HTTPException(
            status_code=400,
            detail="Selected standard is missing a valid incomplete_days value for incomplete evaluations.",
        )
    return date_awarded + timedelta(days=incomplete_days)

# ------------------------------------------------------------
# Matrix
# ------------------------------------------------------------
@router.get("/matrix")
def get_certification_matrix(
    affiliation_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return build_certification_matrix(db, current_user, affiliation_id=affiliation_id)


# ------------------------------------------------------------
# Issue (create) certification
# ------------------------------------------------------------
@router.post("/", response_model=CertificationOut)
def issue_certification(
    payload: CertificationCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    _mfa=Depends(require_mfa_verified),
):
    evaluation_complete = bool(getattr(payload, "evaluation_complete", True))
    requires_co = bool(getattr(payload, "requires_co_evaluator", False))
    old_requires_co = None

    if requires_co:
        status_val = "pending"
    else:
        status_val = "active" if evaluation_complete else "incomplete"

    if status_val == "incomplete":
        if not (payload.comment and payload.comment.strip()):
            raise HTTPException(status_code=422, detail="Incomplete certifications require a comment.")

    if status_val in ("active", "incomplete") and payload.expires_at is None:
        raise HTTPException(status_code=422, detail="expires_at is required for active and incomplete certifications.")
    
    standard = (
        db.query(Standard)
        .filter(Standard.standard_id == payload.standard_id)
        .first()
)
    if not standard:
        raise HTTPException(status_code=404, detail="Standard not found")
    
    expires_at = compute_default_expiration(
        date_awarded=payload.date_awarded,
        evaluation_complete=bool(payload.evaluation_complete),
        standard=standard,
    )

    issued_at = datetime.utcnow().replace(microsecond=0)

    requires_co = bool(getattr(payload, "requires_co_evaluator", False))

    if not current_user.signature_url:
        raise HTTPException(
            status_code=400,
            detail="A saved signature is required before issuing a certification",
        )
    
    if not (payload.location or "").strip():
        raise HTTPException(status_code=400, detail="Location is required")

    if requires_co:
        status_val = "pending"
    else:
        status_val = "active" if evaluation_complete else "incomplete"

    cert = Certification(
        team_id=payload.team_id,
        standard_id=payload.standard_id,
        date_awarded=payload.date_awarded,
        expires_at=expires_at,
        status=status_val,
        location=payload.location,
        comment=getattr(payload, "comment", None),
        supervisor_id=current_user.user_id,
        requires_co_evaluator=requires_co,
        evaluation_complete=getattr(payload, "evaluation_complete", True),
        last_actor_user_id=current_user.user_id,
        issuer_user_id=current_user.user_id,
        issued_at=issued_at,
        seal_version=2,
        signature_url=current_user.signature_url,
        signature_hash=current_user.signature_hash,
        signature_updated_at=current_user.signature_updated_at,
    )

    db.add(cert)
    db.flush()  # ensure certification_id exists
    # OPTIONAL but nice: db.refresh(cert) to ensure DB-normalized values are used
    # db.refresh(cert)
    cert.seal_hash = compute_seal_hash(cert=cert)
    # Freeze signer signature onto this certification (so it never changes later)
    signer = db.query(User).filter(User.user_id == current_user.user_id).one()

    cert.supervisor_id = current_user.user_id  # you already have this working
    cert.signature_url = signer.signature_url
    cert.signature_hash = signer.signature_hash
    cert.signature_updated_at = signer.signature_updated_at  # UTC-naive in your DB

    # log.warning("ISSUE CERT: signer=%s sig_url=%s", current_user.user_id, cert.signature_url)

    # Optional guard: if you want to REQUIRE signature to issue
    # if not cert.signature_url or not cert.signature_hash:
    #     raise HTTPException(status_code=422, detail="Please upload your signature before issuing certificates.")

    log_cert_event(
        db,
        cert=cert,
        event_type="issued",
        actor_user_id=current_user.user_id,
        previous_status=None,
        new_status=cert.status,
        evaluation_complete_before=None,
        evaluation_complete_after=cert.evaluation_complete,
        requires_co_evaluator_before=None,
        requires_co_evaluator_after=cert.requires_co_evaluator,
        location_before=None,
        location_after=None,
        comment_before=None,
        comment_after=cert.comment,
        date_awarded_before=None,
        date_awarded_after=None,
        expires_at_before=None,
        expires_at_after=None,
    )

    db.commit()
    db.refresh(cert)
    return cert


# ------------------------------------------------------------
# Update pending (PATCH existing pending cert only)
# ------------------------------------------------------------

def status_str(x) -> str:
    return (getattr(x, "value", x) or "").strip().lower()

@router.patch("/{certification_id}", response_model=CertificationOut)
def update_or_finalize_pending_certification(
    certification_id: int,
    payload: CertificationUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    _mfa=Depends(require_mfa_verified),
):
    cert = db.query(Certification).filter(Certification.certification_id == certification_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certification not found")

    if status_str(cert.status) not in ("pending", "incomplete"):
        raise HTTPException(
            status_code=422,
            detail="Only pending and incomplete certifications can be updated via PATCH.",
        )

    require_evaluator_for_cert(current_user, cert, db)
    forbid_self_certification(db, current_user, cert.team_id)

    old_status = status_str(cert.status)
    old_eval_complete = cert.evaluation_complete
    old_requires_co = bool(cert.requires_co_evaluator)
    old_location = cert.location
    old_comment = cert.comment

    # Desired status: default stays pending unless explicitly finalizing
    desired_status = status_str(getattr(payload, "status", None)) or "pending"
    if cert.requires_co_evaluator and desired_status in ("active", "incomplete"):
        raise HTTPException(
            status_code=422,
            detail="This certification requires co-evaluator approval.",
        )
    if desired_status not in ("pending", "incomplete", "active"):
        raise HTTPException(
            status_code=422,
            detail="Pending or incomplete certifications may only remain pending, remain incomplete, or be finalized to active.",
       )

    # Apply patch fields (never touch team_id/standard_id here)
    if getattr(payload, "date_awarded", None) is not None:
        cert.date_awarded = payload.date_awarded

    if getattr(payload, "expires_at", None) is not None:
        cert.expires_at = payload.expires_at

    if getattr(payload, "location", None) is not None:
        cert.location = payload.location

    if hasattr(payload, "comment") and payload.comment is not None:
        cert.comment = payload.comment

    if payload.evaluation_complete is not None:
        cert.evaluation_complete = payload.evaluation_complete

    # Keep the evaluator who is editing/finalizing
    cert.supervisor_id = current_user.user_id
    cert.last_actor_user_id = current_user.user_id

    if not current_user.signature_url:
        raise HTTPException(
            status_code=400,
            detail="A saved signature is required before updating a certification",
        )

    cert.signature_url = current_user.signature_url
    cert.signature_hash = current_user.signature_hash
    cert.signature_updated_at = current_user.signature_updated_at

    # Common requirements
    if cert.date_awarded is None:
        raise HTTPException(status_code=422, detail="date_awarded is required.")
    if cert.expires_at is None:
        raise HTTPException(status_code=422, detail="expires_at is required.")


    # Incomplete resting state (only valid when co-evaluator is NOT required)
    if desired_status == "incomplete":
        if cert.requires_co_evaluator:
            raise HTTPException(
                status_code=422,
                detail="This certification requires co-evaluator approval and cannot be set to incomplete directly.",
            )
        if not (cert.comment and cert.comment.strip()):
            raise HTTPException(status_code=422, detail="Incomplete certifications require a comment.")
        
        if not (cert.location and cert.location.strip()):
            raise HTTPException(status_code=422, detail=" location is required.")

        cert.status = "incomplete"

        log_cert_event(
            db,
            cert=cert,
            event_type="updated_incomplete",
            actor_user_id=current_user.user_id,
            previous_status=old_status,
            new_status=cert.status,
            evaluation_complete_before=old_eval_complete,
            evaluation_complete_after=cert.evaluation_complete,
            requires_co_evaluator_before=old_requires_co,
            requires_co_evaluator_after=cert.requires_co_evaluator,
            note=cert.comment,
            location_before=old_location,
            location_after=cert.location,
            comment_before=old_comment,
            comment_after=cert.comment,
            date_awarded_before=None,
            date_awarded_after=None,
            expires_at_before=None,
            expires_at_after=None,
        )

        db.commit()
        db.refresh(cert)
        return cert

    # If co-evaluator is required, primary submissions always return to pending
    if cert.requires_co_evaluator:
        cert.status = "pending"
        log_cert_event(
            db,
            cert=cert,
            event_type="updated_pending",
            actor_user_id=current_user.user_id,
            previous_status=old_status,
            new_status=cert.status,
            evaluation_complete_before=old_eval_complete,
            evaluation_complete_after=cert.evaluation_complete,
            requires_co_evaluator_before=old_requires_co,
            requires_co_evaluator_after=cert.requires_co_evaluator,
            note=cert.comment,
            location_before=old_location,
            location_after=cert.location,
            comment_before=old_comment,
            comment_after=cert.comment,
            date_awarded_before=None,
            date_awarded_after=None,
            expires_at_before=None,
            expires_at_after=None,
        )
        # reset prior co-evaluation cycle
        cert.co_evaluator_user_id = None
        cert.co_evaluated_at = None
        # cert.co_evaluator_note = None
        cert.co_signature_url = None
        cert.co_signature_hash = None
        cert.co_signature_updated_at = None

        db.commit()
        db.refresh(cert)
        return cert
    # ---- Finalize to ACTIVE ----
    # If you want to still require a comment on finalization, keep this; otherwise remove it.
    # if not (cert.comment and cert.comment.strip()):
    #     raise HTTPException(status_code=422, detail="A comment is required to finalize a certification.")

    cert.status = "active" if cert.evaluation_complete else "incomplete"

    # Decide what "issued_at" means in your system:
    # - if you want it to represent finalization time, set it now
    cert.issued_at = datetime.utcnow().replace(microsecond=0)

    # Seal/sign only when active
    cert.seal_version = 2

    # Must flush before computing hash if hash uses certification_id
    db.flush()

    cert.seal_hash = compute_seal_hash(cert=cert)

    signer = db.query(User).filter(User.user_id == current_user.user_id).one()
    cert.signature_url = signer.signature_url
    cert.signature_hash = signer.signature_hash
    cert.signature_updated_at = signer.signature_updated_at  # keep your existing timezone handling

    log_cert_event(
        db,
        cert=cert,
        event_type="finalized",
        actor_user_id=current_user.user_id,
        previous_status=old_status,
        new_status=cert.status,
        evaluation_complete_before=old_eval_complete,
        evaluation_complete_after=cert.evaluation_complete,
        requires_co_evaluator_before=old_requires_co,
        requires_co_evaluator_after=cert.requires_co_evaluator,
        note=cert.comment,
        location_before=old_location,
        location_after=cert.location,
        comment_before=old_comment,
        comment_after=cert.comment,
        date_awarded_before=None,
        date_awarded_after=None,
        expires_at_before=None,
        expires_at_after=None,
    )

    db.commit()
    db.refresh(cert)
    return cert

@router.post("/{cert_id}/co-evaluate", response_model=CertificationOut)
def co_evaluate(
    cert_id: int,
    payload: CoEvaluateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _mfa=Depends(require_mfa_verified),
):
    cert = (
        db.query(Certification)
        .filter(Certification.certification_id == cert_id)
        .first()
    )

    old_status = status_str(cert.status)
    old_eval_complete = cert.evaluation_complete
    old_requires_co = bool(cert.requires_co_evaluator)

    if not cert:
        raise HTTPException(status_code=404, detail="Certification not found")

    if status_str(cert.status) != "pending" or not cert.requires_co_evaluator:
        raise HTTPException(status_code=400, detail="Not pending co-evaluation")

    if cert.supervisor_id == current_user.user_id:
        raise HTTPException(status_code=403, detail="Cannot co-evaluate your own certification")

    if cert.co_evaluator_user_id is not None:
        raise HTTPException(status_code=409, detail="Already evaluated")

    require_evaluator_for_cert(current_user, cert, db)
    forbid_self_certification(db, current_user, cert.team_id)

    if payload.action == "reject" and not (payload.note and payload.note.strip()):
        raise HTTPException(status_code=422, detail="Rejecting requires a note.")

    if payload.action == "approve" and not current_user.signature_url:
        raise HTTPException(status_code=400, detail="A saved signature is required before approving a certification")

    cert.co_evaluator_user_id = current_user.user_id
    cert.co_evaluated_at = datetime.utcnow().replace(microsecond=0)
    cert.last_actor_user_id = current_user.user_id
    cert.co_evaluator_note = payload.note.strip() if payload.note and payload.note.strip() else None

    if payload.action == "approve":
        cert.status = "active" if cert.evaluation_complete else "incomplete"
        cert.co_signature_url = current_user.signature_url
        cert.co_signature_hash = current_user.signature_hash
        cert.co_signature_updated_at = current_user.signature_updated_at
    else:
        cert.status = "rejected"

    event_type = "co_approved" if payload.action == "approve" else "co_rejected"

    log_cert_event(
        db,
        cert=cert,
        event_type=event_type,
        actor_user_id=current_user.user_id,
        previous_status=old_status,
        new_status=cert.status,
        evaluation_complete_before=old_eval_complete,
        evaluation_complete_after=cert.evaluation_complete,
        requires_co_evaluator_before=old_requires_co,
        requires_co_evaluator_after=cert.requires_co_evaluator,
        note=(payload.note.strip() if payload.note else None),
        location_before=None,
        location_after=None,
        comment_before=None,
        comment_after=None,
        date_awarded_before=None,
        date_awarded_after=None,
        expires_at_before=None,
        expires_at_after=None,
    )

    db.commit()
    db.refresh(cert)
    return cert

# ------------------------------------------------------------
# Revoke (modify existing row)
# ------------------------------------------------------------
@router.patch("/{certification_id}/revoke", response_model=CertificationOut)
def revoke_certification(
    certification_id: int,
    payload: CertificationRevoke,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cert = db.query(Certification).filter(
        Certification.certification_id == certification_id
    ).first()

    if not cert:
        raise HTTPException(status_code=404, detail="Certification not found")

    require_owner_or_admin(current_user, cert)

    old_status = status_str(cert.status)
    old_eval_complete = cert.evaluation_complete
    old_requires_co = bool(cert.requires_co_evaluator)

    cert.status = "revoked"
    cert.last_actor_user_id = current_user.user_id

    log_cert_event(
        db,
        cert=cert,
        event_type="revoked",
        actor_user_id=current_user.user_id,
        previous_status=old_status,
        new_status=cert.status,
        evaluation_complete_before=old_eval_complete,
        evaluation_complete_after=cert.evaluation_complete,
        requires_co_evaluator_before=old_requires_co,
        requires_co_evaluator_after=cert.requires_co_evaluator,
        note=getattr(payload, "reason", None),
        location_before=None,
        location_after=None,
        comment_before=None,
        comment_after=None,
        date_awarded_before=None,
        date_awarded_after=None,
        expires_at_before=None,
        expires_at_after=None,
    )

    db.commit()
    db.refresh(cert)

    return cert


@router.patch("/{certification_id}/suspend")
def suspend_certification(
    certification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cert = db.query(Certification).filter(
        Certification.certification_id == certification_id
    ).first()

    if not cert:
        raise HTTPException(status_code=404, detail="Certification not found")

    require_owner_or_admin(current_user, cert)

    old_status = status_str(cert.status)
    old_eval_complete = cert.evaluation_complete
    old_requires_co = bool(cert.requires_co_evaluator)

    if cert.status == "revoked":
        raise HTTPException(
            status_code=400,
            detail="Revoked certifications cannot be suspended"
        )

    cert.status = "suspended"
    cert.last_actor_user_id = current_user.user_id

    log_cert_event(
        db,
        cert=cert,
        event_type="suspended",
        actor_user_id=current_user.user_id,
        previous_status=old_status,
        new_status=cert.status,
        evaluation_complete_before=old_eval_complete,
        evaluation_complete_after=cert.evaluation_complete,
        requires_co_evaluator_before=old_requires_co,
        requires_co_evaluator_after=cert.requires_co_evaluator,
        location_before=None,
        location_after=None,
        comment_before=None,
        comment_after=None,
        date_awarded_before=None,
        date_awarded_after=None,
        expires_at_before=None,
        expires_at_after=None,
    )

    db.commit()
    db.refresh(cert)

    return cert

@router.patch("/{certification_id}/unsuspend")
def unsuspend_certification(
    certification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    cert = db.query(Certification).filter(
        Certification.certification_id == certification_id
    ).first()

    if not cert:
        raise HTTPException(status_code=404, detail="Certification not found")

    require_owner_or_admin(current_user, cert)

    old_status = status_str(cert.status)
    old_eval_complete = cert.evaluation_complete
    old_requires_co = bool(cert.requires_co_evaluator)

    if cert.status != "suspended":
        raise HTTPException(
            status_code=400,
            detail="Certification is not suspended"
        )

    cert.status = "active" if cert.evaluation_complete else "incomplete"

    log_cert_event(
        db,
        cert=cert,
        event_type="unsuspended",
        actor_user_id=current_user.user_id,
        previous_status=old_status,
        new_status=cert.status,
        evaluation_complete_before=old_eval_complete,
        evaluation_complete_after=cert.evaluation_complete,
        requires_co_evaluator_before=old_requires_co,
        requires_co_evaluator_after=cert.requires_co_evaluator,
            # 👇 ALWAYS explicitly set to None
        location_before=None,
        location_after=None,
        comment_before=None,
        comment_after=None,
        date_awarded_before=None,
        date_awarded_after=None,
        expires_at_before=None,
        expires_at_after=None,
    )

    db.commit()
    db.refresh(cert)

    return cert


@router.patch("/{cert_id}/correction", response_model=CertificationOut)
def correct_certification(
    cert_id: int,
    payload: CertificationCorrectionIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _mfa=Depends(require_mfa_verified),
):
    cert = (
        db.query(Certification)
        .filter(Certification.certification_id == cert_id)
        .first()
    )
    if not cert:
        raise HTTPException(status_code=404, detail="Certification not found")

    is_admin = user_has_role(current_user, "admin")
    is_issuer = cert.issuer_user_id == current_user.user_id
    effective_status = _determine_status(cert)
    is_expired_or_revoked = effective_status in {"expired", "revoked", "expiring"}

    if not (is_admin or is_issuer or is_expired_or_revoked):
        raise HTTPException(
            status_code=403,
            detail="Only the original issuer, an admin can update a certfication that is not expired/expiring or revoked",
        )

    old_location = cert.location
    old_comment = cert.comment
    old_date_awarded = cert.date_awarded
    old_expires_at = cert.expires_at

    if payload.location is not None:
        new_location = payload.location.strip()
        if not new_location:
            raise HTTPException(status_code=400, detail="Location is required")
        cert.location = new_location

    if payload.comment is not None:
        cert.comment = payload.comment.strip()

    if payload.date_awarded is not None:
        cert.date_awarded = payload.date_awarded

    if payload.expires_at is not None:
        cert.expires_at = payload.expires_at

    if cert.date_awarded and cert.expires_at and cert.expires_at < cert.date_awarded:
        raise HTTPException(status_code=400, detail="Expiration cannot be before award date")

    changed = (
        cert.location != old_location
        or cert.comment != old_comment
        or cert.date_awarded != old_date_awarded
        or cert.expires_at != old_expires_at
    )
    if not changed:
        raise HTTPException(status_code=400, detail="No changes detected")

    log_cert_event(
        db,
        cert=cert,
        event_type="correction",
        actor_user_id=current_user.user_id,
        previous_status=cert.status,
        new_status=cert.status,
        evaluation_complete_before=cert.evaluation_complete,
        evaluation_complete_after=cert.evaluation_complete,
        requires_co_evaluator_before=cert.requires_co_evaluator,
        requires_co_evaluator_after=cert.requires_co_evaluator,
        location_before=old_location,
        location_after=cert.location,
        comment_before=old_comment,
        comment_after=cert.comment,
        date_awarded_before=old_date_awarded,
        date_awarded_after=cert.date_awarded,
        expires_at_before=old_expires_at,
        expires_at_after=cert.expires_at,
    )

    db.commit()
    db.refresh(cert)
    return cert



# ------------------------------------------------------------
# Certificate view DTO (for print page)
# ------------------------------------------------------------
@router.get("/{certification_id}/certificate", response_model=CertificateView)
def get_certificate_view(
    certification_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    cert = (
        db.query(Certification)
        .filter(Certification.certification_id == certification_id)
        .first()
    )
    if not cert:
        raise HTTPException(status_code=404, detail="Certification not found")

    if not can_view_certificate(db, current_user, cert):
        raise HTTPException(status_code=403, detail="Not authorized to view this certificate")

    team = None
    if cert.team_id:
        team = db.query(Team).filter(Team.team_id == cert.team_id).first()

    # Handler user
    handler_user = None
    dog = None
    if team:
        handler = db.query(Handler).filter(Handler.handler_id == team.handler_id).first()
        if handler:
            handler_user = (
                db.query(User)
                .filter(User.user_id == handler.user_id)
                .filter(User.is_active == True)
                .first()
            )
        if team.dog_id:
            dog = db.query(Dog).filter(Dog.dog_id == team.dog_id).first()

    # Standard + discipline
    std = getattr(cert, "standard", None)
    if std is None and cert.standard_id:
        std = db.query(Standard).filter(Standard.standard_id == cert.standard_id).first()
    disc = getattr(std, "discipline", None) if std else None

    # Issuer/supervisor (your signer)
    supervisor = None
    sup_id = getattr(cert, "supervisor_id", None)  # ✅ use supervisor_id
    if sup_id:
        supervisor = db.query(User).filter(User.user_id == sup_id).first()

    last_actor = None
    la_id = getattr(cert, "last_actor_user_id", None)  # ✅ use last_actor_user_id
    if la_id:
        last_actor = db.query(User).filter(User.user_id == la_id).first()

    co_evaluator = None
    co_id = getattr(cert, "co_evaluator_user_id", None)
    if co_id:
        co_evaluator = db.query(User).filter(User.user_id == co_id).first()

    date_awarded = getattr(cert, "date_awarded", None)
    effective_start = getattr(cert, "effective_start", None) or date_awarded

    seal_sc = short_code(cert.seal_hash) if getattr(cert, "seal_hash", None) else None

    return CertificateView(
        certification_id=cert.certification_id,
        handler_name=_full_name(handler_user),
        dog_name=(getattr(dog, "name", None) if dog else None),
        team_name=(getattr(team, "name", None) if team else None),

        discipline_name=((getattr(disc, "name", None) or "—").strip() if disc else "—"),
        standard_name=((getattr(std, "name", None) or "—").strip() if std else "—"),

        date_awarded=date_awarded,
        effective_start=effective_start,
        expires_at=getattr(cert, "expires_at", None),

        location=getattr(cert, "location", None) or "—",
        supervisor_name=_full_name(supervisor),
        last_actor_name=_full_name(last_actor),

        validation_id=seal_sc,
        seal_short_code=seal_sc,

        status=_determine_status(cert),
        requires_co_evaluator=getattr(cert, "requires_co_evaluator", False),
        evaluation_complete=getattr(cert, "evaluation_complete", True),

        issued_at=getattr(cert, "issued_at", None),

        # Primary signature snapshot
        supervisor_signature_url=getattr(cert, "signature_url", None),
        supervisor_signature_hash=getattr(cert, "signature_hash", None),
        supervisor_signature_updated_at=getattr(cert, "signature_updated_at", None),

        # Co-evaluator info
        co_evaluator_user_id=getattr(cert, "co_evaluator_user_id", None),
        co_evaluator_name=_full_name(co_evaluator),
        co_evaluated_at=getattr(cert, "co_evaluated_at", None),

        # Co-evaluator signature snapshot
        co_signature_url=getattr(cert, "co_signature_url", None),
        co_signature_hash=getattr(cert, "co_signature_hash", None),
        co_signature_updated_at=getattr(cert, "co_signature_updated_at", None),

        can_view=True,
    )

# ------------------------------------------------------------
# Public JSON verify: GET /api/certifications/{id}/verify
# (router prefix = /certifications)
# ------------------------------------------------------------
@router.get("/{cert_id}/verify")
def verify_cert(cert_id: int, db: Session = Depends(get_db)):
    cert = db.query(Certification).filter(Certification.certification_id == cert_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")

    stored = getattr(cert, "seal_hash", None)

    if not stored:
        integrity = "UNSEALED"
    else:
        computed = compute_seal_hash(cert=cert)   # ← version-aware function
        integrity = "VALID" if computed == stored else "TAMPERED"

    newer = (
        db.query(Certification)
        .filter(Certification.team_id == cert.team_id)
        .filter(Certification.standard_id == cert.standard_id)
        .order_by(Certification.issued_at.desc(), Certification.certification_id.desc())
        .first()
    )
    superseded_by = None
    if newer and newer.certification_id != cert.certification_id:
        superseded_by = newer.certification_id

    return {
        "certification_id": cert.certification_id,
        "integrity": integrity,
        "standing": _determine_status(cert),
        "seal_hash": stored,
        "short_code": short_code(stored) if stored else None,
        "superseded_by_certification_id": superseded_by,
        "issued_at": getattr(cert, "issued_at", None),
        "revoked_at": getattr(cert, "revoked_at", None),
    }

@router.get("/{cert_id}/events", response_model=list[CertificationEventOut])
def get_certification_events(
    cert_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cert = (
        db.query(Certification)
        .filter(Certification.certification_id == cert_id)
        .first()
    )
    if not cert:
        raise HTTPException(status_code=404, detail="Certification not found")

    if not can_view_certificate(db, current_user, cert):
        raise HTTPException(status_code=403, detail="Not authorized to view this certification")

    rows = (
        db.query(CertificationEvent, User)
        .outerjoin(User, User.user_id == CertificationEvent.actor_user_id)
        .filter(CertificationEvent.certification_id == cert_id)
        .order_by(CertificationEvent.created_at.desc(), CertificationEvent.event_id.desc())
        .all()
    )

    out: list[CertificationEventOut] = []
    for ev, actor in rows:
        out.append(
            CertificationEventOut(
                event_id=ev.event_id,
                certification_id=ev.certification_id,
                event_type=ev.event_type,
                previous_status=ev.previous_status,
                new_status=ev.new_status,
                evaluation_complete_before=ev.evaluation_complete_before,
                evaluation_complete_after=ev.evaluation_complete_after,
                requires_co_evaluator_before=getattr(ev, "requires_co_evaluator_before", None),
                requires_co_evaluator_after=getattr(ev, "requires_co_evaluator_after", None),

                location_before=getattr(ev, "location_before", None),
                location_after=getattr(ev, "location_after", None),
                comment_before=getattr(ev, "comment_before", None),
                comment_after=getattr(ev, "comment_after", None),
                date_awarded_before=getattr(ev, "date_awarded_before", None),
                date_awarded_after=getattr(ev, "date_awarded_after", None),
                expires_at_before=getattr(ev, "expires_at_before", None),
                expires_at_after=getattr(ev, "expires_at_after", None),

                actor_user_id=ev.actor_user_id,
                actor_name=_full_name(actor),
                note=ev.note,
                created_at=ev.created_at,
            )
        )

    return out

@router.get("/{certification_id}/history", response_model=CertificationHistoryOut)
def get_certification_history(
    certification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    SupervisorUser = aliased(User)
    CoEvaluatorUser = aliased(User)
    LastActorUser = aliased(User)
    HandlerUser = aliased(User)

    selected_row = (
        db.query(
            Certification,
            Standard.discipline_id.label("discipline_id"),
            Discipline.name.label("discipline_name"),
        )
        .outerjoin(Standard, Standard.standard_id == Certification.standard_id)
        .outerjoin(Discipline, Discipline.discipline_id == Standard.discipline_id)
        .filter(Certification.certification_id == certification_id)
        .first()
    )

    if not selected_row:
        raise HTTPException(status_code=404, detail="Certification not found")

    selected, selected_discipline_id, selected_discipline_name = selected_row

    # existing permission helper goes here
    # require_can_view_cert(...)

    if not selected.team_id or not selected.standard_id or not selected_discipline_id:
        raise HTTPException(
            status_code=400,
            detail="Selected certification is missing lineage fields",
        )

    rows = (
        db.query(
            Certification,
            Standard.discipline_id.label("discipline_id"),
            Discipline.name.label("discipline_name"),
            Standard.name.label("standard_name"),
            SupervisorUser.user_id.label("supervisor_id"),
            SupervisorUser.first_name.label("supervisor_first"),
            SupervisorUser.last_name.label("supervisor_last"),
            CoEvaluatorUser.user_id.label("co_evaluator_id"),
            CoEvaluatorUser.first_name.label("co_first"),
            CoEvaluatorUser.last_name.label("co_last"),
            LastActorUser.user_id.label("last_actor_id"),
            LastActorUser.first_name.label("last_first"),
            LastActorUser.last_name.label("last_last"),
        )
        .outerjoin(Standard, Standard.standard_id == Certification.standard_id)
        .outerjoin(Discipline, Discipline.discipline_id == Standard.discipline_id)
        .outerjoin(
            SupervisorUser,
            SupervisorUser.user_id == Certification.supervisor_id,
        )
        .outerjoin(
            CoEvaluatorUser,
            CoEvaluatorUser.user_id == Certification.co_evaluator_user_id,
        )
        .outerjoin(
            LastActorUser,
            LastActorUser.user_id == Certification.last_actor_user_id,
        )
        .filter(Certification.team_id == selected.team_id)
        .filter(Standard.discipline_id == selected_discipline_id)
        .order_by(
            case((Certification.date_awarded.is_(None), 1), else_=0),
            Certification.date_awarded.desc(),
            case((Certification.issued_at.is_(None), 1), else_=0),
            Certification.issued_at.desc(),
            Certification.certification_id.desc(),
        )
        .all()
    )

    # 4) Team / handler / dog labels
    team_info = (
        db.query(
            Team.team_id.label("team_id"),
            HandlerUser.first_name.label("handler_first"),
            HandlerUser.last_name.label("handler_last"),
            Dog.name.label("dog_name"),
        )
        .outerjoin(Handler, Handler.handler_id == Team.handler_id)
        .outerjoin(HandlerUser, HandlerUser.user_id == Handler.user_id)
        .outerjoin(Dog, Dog.dog_id == Team.dog_id)
        .filter(Team.team_id == selected.team_id)
        .first()
    )

    if not team_info:
        raise HTTPException(status_code=404, detail="Team not found")

    handler_name = " ".join(
        p for p in [team_info.handler_first, team_info.handler_last] if p
    ).strip() or None

    dog_name = team_info.dog_name
    team_name = f"{handler_name or 'Unknown Handler'} / {dog_name or 'Unknown Dog'}"

    def full_name(first, last):
        return " ".join([p for p in [first, last] if p]).strip() or None

    out_rows = []

    for (
        cert,
        discipline_id,
        discipline_name,
        standard_name,
        supervisor_id,
        supervisor_first,
        supervisor_last,
        co_evaluator_id,
        co_first,
        co_last,
        last_actor_id,
        last_first,
        last_last,
    ) in rows:
        out_rows.append(
            CertificationHistoryRowOut(
                certification_id=cert.certification_id,
                team_id=cert.team_id,
                team_name=team_name,
                handler_name=handler_name,
                dog_name=dog_name,
                discipline_id=discipline_id,
                discipline_name=discipline_name,
                standard_id=cert.standard_id,
                standard_name=standard_name,
                status=_determine_status(cert).upper(),
                date_awarded=cert.date_awarded.isoformat() if cert.date_awarded else None,
                effective_start=cert.effective_start.isoformat() if getattr(cert, "effective_start", None) else None,
                expires_at=cert.expires_at.isoformat() if cert.expires_at else None,
                issued_at=cert.issued_at.isoformat() if cert.issued_at else None,
                location=getattr(cert, "location", None),
                supervisor_id=supervisor_id,
                supervisor_name=full_name(supervisor_first, supervisor_last),
                co_evaluator_user_id=co_evaluator_id,
                co_evaluator_name=full_name(co_first, co_last),
                co_evaluated_at=cert.co_evaluated_at.isoformat() if getattr(cert, "co_evaluated_at", None) else None,
                co_evaluator_note=getattr(cert, "co_evaluator_note", None),
                last_actor_user_id=last_actor_id,
                last_actor_name=full_name(last_first, last_last),
                supervisor_signature_updated_at=(
                    cert.signature_updated_at.isoformat()
                    if getattr(cert, "signature_updated_at", None)
                    else None
                ),
                co_signature_updated_at=(
                    cert.co_signature_updated_at.isoformat()
                    if getattr(cert, "co_signature_updated_at", None)
                    else None
                ),
                comment=getattr(cert, "comment", None),
            )
        )

    return CertificationHistoryOut(
        selected_certification_id=selected.certification_id,
        lineage_key=f"team:{selected.team_id}-discipline:{selected_discipline_id}",
        team_id=selected.team_id,
        team_name=team_name,
        handler_name=handler_name,
        dog_name=dog_name,
        discipline_id=selected_discipline_id,
        discipline_name=selected_discipline_name,
        rows=out_rows,
    )