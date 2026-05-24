from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db  # adjust
from app.utils.auth import get_current_user  # adjust
from app.models.user import User
from app.models.handler import Affiliation
from app.schemas.public_schema import PublicAffiliationOut

router = APIRouter(prefix="/api/public", tags=["Public"])


@router.get("/affiliations", response_model=List[PublicAffiliationOut])
def public_affiliations(db: Session = Depends(get_db)):
    rows = (
        db.query(Affiliation)
        .filter(Affiliation.is_active.is_(True))
        .order_by(
            (Affiliation.sortorder.is_(None)).asc(),
            Affiliation.sortorder.asc(),
            Affiliation.name.asc(),
        )
        .all()
    )

    # Explicit mapping (safe even if orm/from_attributes changes later)
    return [
        PublicAffiliationOut(
            affiliation_id=a.affiliation_id,
            name=a.name,
            callout_line=getattr(a, "callout_line", None),
            sortorder=getattr(a, "sortorder", None),
        )
        for a in rows
    ]

