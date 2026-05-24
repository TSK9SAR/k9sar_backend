from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_

from app.database import get_db, Base
from app.models.handler import Affiliation
from app.models.user import User
from app.schemas.affiliation_schema import (
    AffiliationPublicOut,
    AffiliationPublicDetailOut,
)
from app.models.handler import Affiliation, Handler
from app.models.handler_affiliations import HandlerAffiliation
from app.models.user import User
from app.schemas.affiliation_schema import AffiliationMembershipOut, AffiliationDetailOut
from app.utils.auth import get_current_user, is_evaluator

router = APIRouter(
    prefix="/api/affiliations",
    tags=["Affiliations"],
)


@router.get("/", response_model=List[AffiliationPublicOut])
def list_affiliations(
    q: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Affiliation).filter(Affiliation.is_active.is_(True))

    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Affiliation.name.ilike(like),
                Affiliation.callout_line.ilike(like),
                Affiliation.contact_name.ilike(like),
                Affiliation.phone.ilike(like),
                Affiliation.location.ilike(like),
                Affiliation.url.ilike(like),
            )
        )

    rows = (
        query.order_by(
            Affiliation.sortorder.is_(None),
            Affiliation.sortorder.asc(),
            Affiliation.name.asc(),
        )
        .all()
    )

    return rows


handler_affiliations = Base.metadata.tables["handler_affiliations"]

@router.get("/{affiliation_id}/memberships", response_model=list[AffiliationMembershipOut])
def get_affiliation_memberships(
    affiliation_id: int,
    db: Session = Depends(get_db),
):
    rows = (
        db.query(HandlerAffiliation, Handler, User)
        .join(Handler, Handler.handler_id == HandlerAffiliation.handler_id)
        .join(User, User.user_id == Handler.user_id)
        .options(joinedload(User.roles))
        .filter(
            HandlerAffiliation.affiliation_id == affiliation_id,
            HandlerAffiliation.ended_at.is_(None),
        )
        .order_by(User.last_name.asc(), User.first_name.asc())
        .all()
    )

    out = []
    for ha, h, u in rows:
        role_names = sorted(
            {
                (getattr(r, "role_name", "") or "").strip().lower()
                for r in (getattr(u, "roles", []) or [])
                if getattr(r, "role_name", None)
            }
        )

        evaluator = "Evaluator" if is_evaluator(db, u.user_id) else None

        out.append(
            AffiliationMembershipOut(
                handler_id=h.handler_id,
                user_id=u.user_id,
                first_name=u.first_name,
                last_name=u.last_name,
                phone=u.phone,
                email=u.email,
                role=", ".join(role_names) if role_names else None,
                evaluator=evaluator,
                address_line1=getattr(u, "address_line1", None),
                city=getattr(u, "city", None),
            )
        )

    return out


@router.get("/{affiliation_id}", response_model=AffiliationDetailOut)
def get_affiliation_detail(
    affiliation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = (
        db.query(Affiliation)
        .filter(
            Affiliation.affiliation_id == affiliation_id,
            Affiliation.is_active.is_(True),
        )
        .first()
    )

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Affiliation not found",
        )

    return row