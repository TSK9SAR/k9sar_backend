from __future__ import annotations

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.utils.auth import get_current_user
from app.utils.authz import require_can_manage_affiliation
from app.utils.affiliation_scope import (
    get_affiliation_scope,
    require_supervisor_or_admin,
)
from app.models.user import User
from app.models.handler import Affiliation, Handler
from app.models.handler_affiliations import (
    HandlerAffiliation,
    AffiliationChangeRequest,
    ReviewNoteIn,
)
from app.schemas.affiliation_memberships import (
    AffiliationChangeRequestOut,
    AffiliationMini,
)

router = APIRouter(prefix="/api/supervisor", tags=["Affiliation Requests (Supervisor)"])


def _resolve_handler_name(db: Session, handler_id: int) -> str:
    row = (
        db.query(Handler, User)
        .join(User, User.user_id == Handler.user_id)
        .filter(Handler.handler_id == handler_id)
        .first()
    )

    if not row:
        return f"Handler #{handler_id}"

    handler, user = row

    display = getattr(user, "display_name", None)
    if display:
        return display

    first = getattr(user, "first_name", None)
    last = getattr(user, "last_name", None)
    if first or last:
        return f"{first or ''} {last or ''}".strip()

    email = getattr(user, "email", None)
    if email:
        return email

    return f"Handler #{handler_id}"


def _request_to_out(
    db: Session,
    req: AffiliationChangeRequest,
    aff: Affiliation,
) -> AffiliationChangeRequestOut:
    return AffiliationChangeRequestOut(
        request_id=req.request_id,
        handler_id=req.handler_id,
        handler_name=_resolve_handler_name(db, req.handler_id),
        affiliation=AffiliationMini(
            affiliation_id=aff.affiliation_id,
            name=aff.name,
        ),
        action=req.action,
        status=req.status,
        requested_at=req.requested_at,
        request_note=req.request_note,
        reviewed_at=req.reviewed_at,
        review_note=req.review_note,
    )


@router.get("/kpis")
def supervisor_kpis(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_supervisor_or_admin(db, current_user)

    scope = get_affiliation_scope(db, current_user)

    q = db.query(func.count(AffiliationChangeRequest.request_id)).filter(
        AffiliationChangeRequest.status == "pending"
    )

    if scope is not None:
        if not scope:
            return {"pending_affiliations": 0}
        q = q.filter(AffiliationChangeRequest.affiliation_id.in_(scope))

    pending = q.scalar() or 0
    return {"pending_affiliations": int(pending)}


@router.get("/affiliation-requests", response_model=list[AffiliationChangeRequestOut])
def list_affiliation_requests(
    status_filter: str = "pending",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_supervisor_or_admin(db, current_user)

    if status_filter not in ("pending", "approved", "rejected"):
        raise HTTPException(status_code=400, detail="Invalid status filter")

    scope = get_affiliation_scope(db, current_user)

    q = (
        db.query(AffiliationChangeRequest, Affiliation, Handler)
        .join(
            Affiliation,
            Affiliation.affiliation_id == AffiliationChangeRequest.affiliation_id,
        )
        .join(
            Handler,
            Handler.handler_id == AffiliationChangeRequest.handler_id,
        )
        .filter(AffiliationChangeRequest.status == status_filter)
    )

    if scope is not None:
        if not scope:
            return []
        q = q.filter(AffiliationChangeRequest.affiliation_id.in_(scope))

    rows = q.order_by(AffiliationChangeRequest.requested_at.asc()).all()

    out: List[AffiliationChangeRequestOut] = []
    for req, aff, _handler in rows:
        out.append(_request_to_out(db, req, aff))
    return out


@router.post("/affiliation-requests/{request_id}/approve", response_model=AffiliationChangeRequestOut)
def approve_affiliation_request(
    request_id: int,
    payload: ReviewNoteIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    req = (
        db.query(AffiliationChangeRequest)
        .filter(AffiliationChangeRequest.request_id == request_id)
        .first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    require_can_manage_affiliation(db, current_user, req.affiliation_id)

    if req.status != "pending":
        raise HTTPException(status_code=400, detail=f"Request is {req.status}, not pending")

    if req.action == "add":
        active = (
            db.query(HandlerAffiliation)
            .filter(
                HandlerAffiliation.handler_id == req.handler_id,
                HandlerAffiliation.affiliation_id == req.affiliation_id,
                HandlerAffiliation.ended_at.is_(None),
            )
            .first()
        )
        if not active:
            db.add(
                HandlerAffiliation(
                    handler_id=req.handler_id,
                    affiliation_id=req.affiliation_id,
                    started_at=datetime.utcnow(),
                    started_by_user_id=current_user.user_id,
                    note=req.request_note,
                )
            )

    elif req.action == "remove":
        active = (
            db.query(HandlerAffiliation)
            .filter(
                HandlerAffiliation.handler_id == req.handler_id,
                HandlerAffiliation.affiliation_id == req.affiliation_id,
                HandlerAffiliation.ended_at.is_(None),
            )
            .first()
        )
        if active:
            active.ended_at = datetime.utcnow()
            active.ended_by_user_id = current_user.user_id
            if (payload.review_note or "").strip():
                active.note = (active.note or "") + (
                    ("\n" if active.note else "") + payload.review_note.strip()
                )
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

    aff = (
        db.query(Affiliation)
        .filter(Affiliation.affiliation_id == req.affiliation_id)
        .first()
    )
    if not aff:
        raise HTTPException(status_code=404, detail="Affiliation not found")

    req.status = "approved"
    req.reviewed_at = datetime.utcnow()
    req.review_note = payload.review_note or None
    req.reviewed_by_user_id = current_user.user_id

    db.commit()
    db.refresh(req)

    return _request_to_out(db, req, aff)


@router.post("/affiliation-requests/{request_id}/reject", response_model=AffiliationChangeRequestOut)
def reject_affiliation_request(
    request_id: int,
    payload: ReviewNoteIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_supervisor_or_admin(db, current_user)

    req = (
        db.query(AffiliationChangeRequest)
        .filter(AffiliationChangeRequest.request_id == request_id)
        .first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    if req.status != "pending":
        raise HTTPException(status_code=400, detail="Request is not pending")

    aff = (
        db.query(Affiliation)
        .filter(Affiliation.affiliation_id == req.affiliation_id)
        .first()
    )
    if not aff:
        raise HTTPException(status_code=404, detail="Affiliation not found")

    require_can_manage_affiliation(db, current_user, req.affiliation_id)

    req.status = "rejected"
    req.reviewed_by_user_id = current_user.user_id
    req.reviewed_at = datetime.utcnow()
    req.review_note = payload.review_note or None

    db.commit()
    db.refresh(req)

    return _request_to_out(db, req, aff)