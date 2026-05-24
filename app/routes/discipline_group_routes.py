from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.utils.auth import get_current_user, require_mfa_verified, require_admin

from app.models.discipline_group import DisciplineGroup
from app.models.discipline import Discipline

from app.schemas.discipline_group_schema import (
    DisciplineGroupCreate,
    DisciplineGroupUpdate,
    DisciplineGroupOut,
)

router = APIRouter(prefix="/discipline-groups", tags=["Discipline Groups"])


@router.get("/", response_model=list[DisciplineGroupOut])
def list_groups(
    db: Session = Depends(get_db),
    # current_user=Depends(get_current_user), # Optional: if you want to restrict this endpoint to authenticated users, uncomment this line and the one in the function signature.
):
    # require_admin(current_user) # Optional: if you want to restrict this endpoint to admins only, uncomment this line.
    groups = (
    db.query(DisciplineGroup)
    .filter(DisciplineGroup.name != "Legacy")
    .order_by(DisciplineGroup.sortorder, DisciplineGroup.name)
    .all()
)
    out = []
    for g in groups:
        out.append(
            DisciplineGroupOut(
                group_id=g.group_id,
                name=g.name,
                sortorder=g.sortorder,  # <-- ADD THIS
                discipline_ids=[d.discipline_id for d in (g.disciplines or [])],
                show_operational=bool(g.show_operational),  # <-- ADD THIS
                show_generic=bool(g.show_generic),  # <-- ADD THIS
            )
        )
    return out


@router.post("/", response_model=DisciplineGroupOut, status_code=status.HTTP_201_CREATED)
def create_group(
    payload: DisciplineGroupCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
    _mfa=Depends(require_mfa_verified),  # <-- add this
):

    if payload.name.strip().lower() == "Legacy":
        raise HTTPException(status_code=400, detail="Reserved system group name")

    exists = db.query(DisciplineGroup).filter(DisciplineGroup.name == payload.name).first()
    if exists:
        raise HTTPException(status_code=409, detail="Discipline group name already exists")

    group = DisciplineGroup(name=payload.name)
    db.add(group)
    db.flush()  # get group.group_id

    # Assign disciplines by setting their group_id to this group
    if payload.discipline_ids:
        disciplines = (
            db.query(Discipline)
            .filter(Discipline.discipline_id.in_(payload.discipline_ids))
            .all()
        )
        found_ids = {d.discipline_id for d in disciplines}
        missing = [i for i in payload.discipline_ids if i not in found_ids]
        if missing:
            raise HTTPException(status_code=404, detail=f"Disciplines not found: {missing}")

        for d in disciplines:
            d.group_id = group.group_id

    db.commit()
    db.refresh(group)

    return DisciplineGroupOut(
        group_id=group.group_id,
        name=group.name,
        discipline_ids=[d.discipline_id for d in (group.disciplines or [])],
        show_operational=bool(group.show_operational),
        show_generic=bool(group.show_generic),
    )


@router.put("/{group_id}", response_model=DisciplineGroupOut)
def update_group(
    group_id: int,
    payload: DisciplineGroupUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
    _mfa=Depends(require_mfa_verified),
):

    group = (
        db.query(DisciplineGroup)
        .filter(DisciplineGroup.group_id == group_id)
        .first()
    )
    if not group:
        raise HTTPException(status_code=404, detail="Discipline group not found")

    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="Discipline group name cannot be blank")

        dup = (
            db.query(DisciplineGroup)
            .filter(
                DisciplineGroup.name == name,
                DisciplineGroup.group_id != group_id,
            )
            .first()
        )
        if dup:
            raise HTTPException(status_code=409, detail="Discipline group name already exists")

        group.name = name

    if payload.sortorder is not None:
        group.sortorder = payload.sortorder

    if payload.show_operational is not None:
        group.show_operational = 1 if payload.show_operational else 0

    if payload.show_generic is not None:
        group.show_generic = 1 if payload.show_generic else 0

    # If discipline_ids is provided: REPLACE the group's disciplines set
    if payload.discipline_ids is not None:
        legacy = (
            db.query(DisciplineGroup)
            .filter(DisciplineGroup.name == "Legacy")
            .first()
        )
        if not legacy:
            raise HTTPException(
                status_code=500,
                detail="Legacy group missing; cannot reassign disciplines safely",
            )

        current_discs = (
            db.query(Discipline)
            .filter(Discipline.group_id == group_id)
            .all()
        )
        for d in current_discs:
            d.group_id = legacy.group_id

        if payload.discipline_ids:
            disciplines = (
                db.query(Discipline)
                .filter(Discipline.discipline_id.in_(payload.discipline_ids))
                .all()
            )
            found_ids = {d.discipline_id for d in disciplines}
            missing = [i for i in payload.discipline_ids if i not in found_ids]
            if missing:
                raise HTTPException(status_code=404, detail=f"Disciplines not found: {missing}")

            for d in disciplines:
                d.group_id = group_id

    db.commit()
    db.refresh(group)

    return DisciplineGroupOut(
        group_id=group.group_id,
        name=group.name,
        sortorder=group.sortorder,
        discipline_ids=[d.discipline_id for d in (group.disciplines or [])],
        show_operational=bool(group.show_operational),
        show_generic=bool(group.show_generic),
    )


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
    _mfa=Depends(require_mfa_verified),  # <-- add this
):

    group = db.query(DisciplineGroup).filter(DisciplineGroup.group_id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Discipline group not found")

    legacy = db.query(DisciplineGroup).filter(DisciplineGroup.name == "Legacy").first()
    if not legacy:
        raise HTTPException(status_code=500, detail="Legacy group missing; cannot delete groups safely")

    if group.group_id == legacy.group_id:
        raise HTTPException(status_code=400, detail="Cannot delete Legacy group")

    # Move disciplines to Legacy so FK NOT NULL constraint isn't violated
    db.query(Discipline).filter(Discipline.group_id == group_id).update(
        {Discipline.group_id: legacy.group_id},
        synchronize_session=False,
    )

    # Clean user associations
    group.evaluators = []

    db.delete(group)
    db.commit()
    return None
