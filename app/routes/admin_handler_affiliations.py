from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from sqlalchemy import asc
from typing import Optional
from app.database import get_db
from app.utils.auth import get_current_user, require_admin

from app.models.handler import Affiliation
from app.schemas.affiliation_schema import AffiliationCreate, AffiliationUpdate, AffiliationOut
from app.models.user import User
from app.models.handler_affiliations import HandlerAffiliation
from app.schemas.affiliation_memberships import HandlerAffiliationsResponse, HandlerAffiliationOut, AffiliationMini

from typing import Optional
from datetime import datetime

router = APIRouter(prefix="/admin", tags=["admin-handler-affiliations"])


# GET /api/admin/handlers/{handler_id}/affiliations
@router.get("/handlers/{handler_id}/affiliations", response_model=HandlerAffiliationsResponse)
def admin_list_handler_affiliations(
    handler_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):

    rows = (
        db.query(HandlerAffiliation, Affiliation)
        .join(Affiliation, Affiliation.affiliation_id == HandlerAffiliation.affiliation_id)
        .filter(HandlerAffiliation.handler_id == handler_id)
        .order_by(HandlerAffiliation.ended_at.isnot(None), HandlerAffiliation.started_at.desc())
        .all()
    )

    current, past = [], []
    for ha, a in rows:
        item = HandlerAffiliationOut(
            affiliation=AffiliationMini(affiliation_id=a.affiliation_id, name=a.name),
            started_at=ha.started_at,
            ended_at=ha.ended_at,
            note=ha.note,
        )
        (current if ha.ended_at is None else past).append(item)

    return HandlerAffiliationsResponse(current=current, past=past)


class AdminAffiliationAddIn(BaseModel):
    affiliation_id: int
    note: Optional[str] = None
    started_at: Optional[datetime] = None  # optional backdate

@router.post("/handlers/{handler_id}/affiliations", response_model=HandlerAffiliationOut, status_code=201)
def admin_add_handler_affiliation(
    handler_id: int,
    payload: AdminAffiliationAddIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):

    aff = db.query(Affiliation).filter(Affiliation.affiliation_id == payload.affiliation_id).first()
    if not aff:
        raise HTTPException(status_code=404, detail="Affiliation not found")

    active = db.query(HandlerAffiliation).filter(
        HandlerAffiliation.handler_id == handler_id,
        HandlerAffiliation.affiliation_id == payload.affiliation_id,
        HandlerAffiliation.ended_at.is_(None),
    ).first()
    if active:
        raise HTTPException(status_code=400, detail="Handler is already affiliated")

    ha = HandlerAffiliation(
        handler_id=handler_id,
        affiliation_id=payload.affiliation_id,
        started_at=payload.started_at or datetime.utcnow(),
        started_by_user_id=current_user.user_id,
        note=(payload.note or None),
    )
    db.add(ha)
    db.commit()
    db.refresh(ha)

    return HandlerAffiliationOut(
        affiliation=AffiliationMini(affiliation_id=aff.affiliation_id, name=aff.name),
        started_at=ha.started_at,
        ended_at=ha.ended_at,
        note=ha.note,
    )

class AdminAffiliationEndIn(BaseModel):
    note: Optional[str] = None
    ended_at: Optional[datetime] = None  # optional backdate

@router.post("/handlers/{handler_id}/affiliations/{affiliation_id}/end", response_model=HandlerAffiliationOut)
def admin_end_handler_affiliation(
    handler_id: int,
    affiliation_id: int,
    payload: AdminAffiliationEndIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):

    ha = db.query(HandlerAffiliation).filter(
        HandlerAffiliation.handler_id == handler_id,
        HandlerAffiliation.affiliation_id == affiliation_id,
        HandlerAffiliation.ended_at.is_(None),
    ).first()
    if not ha:
        raise HTTPException(status_code=404, detail="No active affiliation to end")

    ha.ended_at = payload.ended_at or datetime.utcnow()
    ha.ended_by_user_id = current_user.user_id

    if (payload.note or "").strip():
        ha.note = (ha.note or "")
        ha.note = (ha.note + ("\n" if ha.note else "") + payload.note.strip())

    aff = db.query(Affiliation).filter(Affiliation.affiliation_id == affiliation_id).first()
    if not aff:
        # still end; but keep response stable
        name = f"Affiliation #{affiliation_id}"
        aff_id = affiliation_id
    else:
        name = aff.name
        aff_id = aff.affiliation_id

    db.commit()
    db.refresh(ha)

    return HandlerAffiliationOut(
        affiliation=AffiliationMini(affiliation_id=aff_id, name=name),
        started_at=ha.started_at,
        ended_at=ha.ended_at,
        note=ha.note,
    )