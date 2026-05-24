from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.models.discipline import Discipline
from app.models.standard import Standard
from app.schemas.standard_schema import DisciplineWithLatestStandardOut

from datetime import date
from sqlalchemy import func, and_
from sqlalchemy.orm import aliased

router = APIRouter(prefix="/public", tags=["Public"])

@router.get("/standards", response_model=List[DisciplineWithLatestStandardOut])
def public_standards_by_discipline(db: Session = Depends(get_db)):
    today = date.today()

    latest_dt_subq = (
        db.query(
            Standard.discipline_id.label("discipline_id"),
            func.max(Standard.effective_date).label("max_eff"),
        )
        .filter(Standard.effective_date <= today)
        .group_by(Standard.discipline_id)
        .subquery()
    )

    latest_id_subq = (
        db.query(
            Standard.discipline_id.label("discipline_id"),
            func.max(Standard.standard_id).label("max_id"),
        )
        .join(
            latest_dt_subq,
            and_(
                latest_dt_subq.c.discipline_id == Standard.discipline_id,
                latest_dt_subq.c.max_eff == Standard.effective_date,
            ),
        )
        .group_by(Standard.discipline_id)
        .subquery()
    )

    S = aliased(Standard)

    rows = (
        db.query(Discipline, S)
        .outerjoin(latest_id_subq, latest_id_subq.c.discipline_id == Discipline.discipline_id)
        .outerjoin(S, S.standard_id == latest_id_subq.c.max_id)
        .order_by(Discipline.sortorder.asc(), Discipline.name.asc())
        .all()
    )

    out: List[DisciplineWithLatestStandardOut] = []
    for d, s in rows:
        out.append(
            DisciplineWithLatestStandardOut(
                discipline_id=d.discipline_id,
                group_id=d.group_id,
                name=d.name,
                description=d.description,
                sortorder=d.sortorder,
                standard=s,  # can be None; pydantic will handle
            )
        )

    return out
