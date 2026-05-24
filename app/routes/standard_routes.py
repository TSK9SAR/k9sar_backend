# app/routes/standard_routes.py
from typing import List, Optional
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.standard_schema import StandardCreate, StandardUpdate, StandardOut
from app.models.standard import Standard as StandardModel
from app.models.standard import Standard
from app.models.discipline import Discipline
from app.models.user import User
from app.models.discipline_group import DisciplineGroup
from app.schemas.standard_schema import StandardOut
from app.utils.auth import get_current_user, require_mfa_verified, require_admin


router = APIRouter(prefix="/standards", tags=["Standards"])


@router.post("/", response_model=StandardOut, status_code=status.HTTP_201_CREATED)
def create_standard(
    payload: StandardCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),   # <-- add this
    _mfa=Depends(require_mfa_verified),
):
    # Optional: enforce unique name (global)
    existing = (
        db.query(StandardModel)
        .filter(StandardModel.name == payload.name)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A standard with this name already exists.",
        )

    standard_obj = StandardModel(
        discipline_id=payload.discipline_id,
        name=payload.name,
        url=payload.url,
        summary_md=payload.summary_md,
        effective_date=payload.effective_date,
        incomplete_days=payload.incomplete_days,
        effective_days=payload.effective_days,
    )


    db.add(standard_obj)
    db.commit()
    db.refresh(standard_obj)
    return standard_obj


@router.get("/", response_model=List[StandardOut])
def list_standards(
    discipline_id: int | None = None,
    section: str = "operational",   # operational | generic
    db: Session = Depends(get_db),
):
    rows_query = (
        db.query(
            Standard,
            Discipline.name.label("discipline_name"),
            Discipline.sortorder.label("discipline_sortorder"),
            Discipline.group_id.label("group_id"),
            DisciplineGroup.name.label("discipline_group_name"),
            DisciplineGroup.sortorder.label("discipline_group_sortorder"),
        )
        .outerjoin(Discipline, Discipline.discipline_id == Standard.discipline_id)
        .outerjoin(DisciplineGroup, DisciplineGroup.group_id == Discipline.group_id)
    )

    if discipline_id:
        # ADMIN / EDIT MODE
        # Fetch everything for that discipline, regardless of visibility flags
        rows_query = rows_query.filter(Standard.discipline_id == discipline_id)
    else:
        # PUBLIC MODE
        if section == "generic":
            rows_query = rows_query.filter(Discipline.show_generic.is_(True))
        else:
            rows_query = rows_query.filter(DisciplineGroup.show_operational.is_(True))
            rows_query = rows_query.filter(Discipline.show_operational.is_(True))

    rows = (
        rows_query
        .order_by(
            DisciplineGroup.sortorder.asc(),
            Discipline.sortorder.asc(),
            Standard.effective_date.desc(),
            Standard.name.asc(),
        )
        .all()
    )

    out: List[StandardOut] = []
    for std, disc_name, disc_sortorder, group_id, group_name, group_sortorder in rows:
        try:
            item = StandardOut.model_validate(std)
        except AttributeError:
            item = StandardOut.from_orm(std)

        item.discipline_name = disc_name
        item.discipline_sortorder = disc_sortorder
        item.discipline_group_id = group_id
        item.discipline_group_name = group_name
        item.discipline_group_sortorder = group_sortorder

        out.append(item)

    return out

@router.get("/admin/all", response_model=List[StandardOut])
def list_all_standards_for_admin(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    _mfa=Depends(require_mfa_verified),
):

    rows = (
        db.query(
            Standard,
            Discipline.name.label("discipline_name"),
            Discipline.group_id.label("group_id"),
            DisciplineGroup.name.label("discipline_group_name"),
        )
        .outerjoin(Discipline, Discipline.discipline_id == Standard.discipline_id)
        .outerjoin(DisciplineGroup, DisciplineGroup.group_id == Discipline.group_id)
        .order_by(Standard.standard_id.asc())
        .all()
    )

    out: List[StandardOut] = []
    for std, disc_name, group_id, group_name in rows:
        try:
            item = StandardOut.model_validate(std)
        except AttributeError:
            item = StandardOut.from_orm(std)

        item.discipline_name = disc_name
        item.discipline_group_id = group_id
        item.discipline_group_name = group_name
        out.append(item)

    return out


@router.get("/current", response_model=StandardOut | None)
def get_applicable_standard(
    discipline_id: int,
    on_date: date | None = None,
    db: Session = Depends(get_db),
) -> StandardOut | None:
    standard_obj = (
        db.query(StandardModel)
        .filter(
            StandardModel.discipline_id == discipline_id,
            StandardModel.effective_date <= (on_date or date.today()),
        )
        .order_by(StandardModel.effective_date.desc())
        .first()
    )
    return standard_obj


@router.get("/{standard_id}", response_model=StandardOut)
def get_standard_by_id(
    standard_id: int,
    db: Session = Depends(get_db),
):
    standard_obj = (
        db.query(StandardModel)
        .filter(StandardModel.standard_id == standard_id)
        .first()
    )
    if not standard_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Standard not found.",
        )
    return standard_obj


@router.put("/{standard_id}", response_model=StandardOut)
def update_standard(
    standard_id: int,
    payload: StandardUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    _mfa=Depends(require_mfa_verified),
):

    standard_obj = (
        db.query(StandardModel)
        .filter(StandardModel.standard_id == standard_id)
        .first()
    )
    if not standard_obj:
        raise HTTPException(status_code=404, detail="Standard not found.")

    try:
        update_data = payload.model_dump(exclude_unset=True)
    except AttributeError:
        update_data = payload.dict(exclude_unset=True)

    for field, value in update_data.items():
        setattr(standard_obj, field, value)

    db.commit()
    db.refresh(standard_obj)
    return standard_obj
