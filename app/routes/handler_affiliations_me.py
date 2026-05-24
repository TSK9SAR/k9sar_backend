from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db  # adjust
from app.utils.auth import get_current_user  # adjust
from app.models.user import User
from app.models.handler import Handler
from app.models.handler import Affiliation
from app.models.handler_affiliations import HandlerAffiliation, AffiliationChangeRequest

from app.schemas.affiliation_memberships import (
    HandlerAffiliationsResponse,
    HandlerAffiliationOut,
    AffiliationMini,
    AffiliationChangeRequestCreate,
    AffiliationChangeRequestOutHandler,
)

router = APIRouter(prefix="/api/handlers/me", tags=["Handler Affiliations (Me)"])


def _get_my_handler(db: Session, current_user: User) -> Handler:
    # Adjust this to your actual user->handler linkage
    h = db.query(Handler).filter(Handler.user_id == current_user.user_id).first()
    if not h:
        raise HTTPException(status_code=404, detail="No handler profile for current user")
    return h


@router.get("/affiliations", response_model=HandlerAffiliationsResponse)
def my_affiliations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    handler = _get_my_handler(db, current_user)

    rows = (
        db.query(HandlerAffiliation, Affiliation)
        .join(Affiliation, Affiliation.affiliation_id == HandlerAffiliation.affiliation_id)
        .filter(HandlerAffiliation.handler_id == handler.handler_id)
        .order_by(HandlerAffiliation.ended_at.isnot(None), HandlerAffiliation.started_at.desc())
        .all()
    )

    current: List[HandlerAffiliationOut] = []
    past: List[HandlerAffiliationOut] = []

    for ha, a in rows:
        item = HandlerAffiliationOut(
            affiliation=AffiliationMini(affiliation_id=a.affiliation_id, name=a.name),
            started_at=ha.started_at,
            ended_at=ha.ended_at,
            note=ha.note,
        )
        if ha.ended_at is None:
            current.append(item)
        else:
            past.append(item)

    return HandlerAffiliationsResponse(current=current, past=past)

@router.post("/affiliation-requests", response_model=AffiliationChangeRequestOutHandler, status_code=201)
def create_affiliation_request(
    payload: AffiliationChangeRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    handler = _get_my_handler(db, current_user)

    aff = db.query(Affiliation).filter(Affiliation.affiliation_id == payload.affiliation_id).first()
    if not aff:
        raise HTTPException(status_code=404, detail="Affiliation not found")

    # Check current membership state
    active_membership = (
        db.query(HandlerAffiliation)
        .filter(
            HandlerAffiliation.handler_id == handler.handler_id,
            HandlerAffiliation.affiliation_id == payload.affiliation_id,
            HandlerAffiliation.ended_at.is_(None),
        )
        .first()
    )

    if payload.action == "add" and active_membership:
        raise HTTPException(status_code=400, detail="Already affiliated")
    if payload.action == "remove" and not active_membership:
        raise HTTPException(status_code=400, detail="No active affiliation to remove")

    # Only one pending request per action
    pending = (
        db.query(AffiliationChangeRequest)
        .filter(
            AffiliationChangeRequest.handler_id == handler.handler_id,
            AffiliationChangeRequest.affiliation_id == payload.affiliation_id,
            AffiliationChangeRequest.action == payload.action,
            AffiliationChangeRequest.status == "pending",
        )
        .first()
    )
    if pending:
        # Return existing pending request (idempotent)
        return AffiliationChangeRequestOutHandler(
            request_id=pending.request_id,
            handler_id=pending.handler_id,
            affiliation=AffiliationMini(affiliation_id=aff.affiliation_id, name=aff.name),
            action=pending.action,
            status=pending.status,
            requested_at=pending.requested_at,
            request_note=pending.request_note,
            reviewed_at=pending.reviewed_at,
            review_note=pending.review_note,
        )

    req = AffiliationChangeRequest(
        handler_id=handler.handler_id,
        affiliation_id=payload.affiliation_id,
        action=payload.action,
        status="pending",
        requested_by_user_id=current_user.user_id,
        requested_at=datetime.utcnow(),
        request_note=(payload.note or None),
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    return AffiliationChangeRequestOutHandler(
        request_id=req.request_id,
        handler_id=req.handler_id,
        affiliation=AffiliationMini(affiliation_id=aff.affiliation_id, name=aff.name),
        action=req.action,
        status=req.status,
        requested_at=req.requested_at,
        request_note=req.request_note,
        reviewed_at=req.reviewed_at,
        review_note=req.review_note,
    )