from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.discipline import Discipline
from app.schemas.discipline_schema import DisciplineCreate, DisciplineOut, DisciplineUpdate
from app.utils.auth import get_current_user, require_mfa_verified, require_admin


router = APIRouter(prefix="/disciplines", tags=["Disciplines"])

@router.post("/", response_model=DisciplineOut)
def create_discipline(item: DisciplineCreate,
                      db: Session = Depends(get_db),
                      current_user = Depends(require_admin), _mfa=Depends(require_mfa_verified)):

    new_disc = Discipline(**item.dict())
    db.add(new_disc)
    db.commit()
    db.refresh(new_disc)
    return new_disc

@router.get("/", response_model=list[DisciplineOut])
def list_disciplines(db: Session = Depends(get_db)):
    return db.query(Discipline).order_by(Discipline.sortorder.asc(), Discipline.name.asc()).all()

@router.put("/{discipline_id}", response_model=DisciplineOut)
def update_discipline(
    discipline_id: int,
    payload: DisciplineUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
    _mfa=Depends(require_mfa_verified),  # <-- add this
):

    disc = db.query(Discipline).filter(Discipline.discipline_id == discipline_id).first()
    if not disc:
        raise HTTPException(status_code=404, detail="Discipline not found")

    # Build update data (pydantic v1/v2 compatible)
    try:
        data = payload.model_dump(exclude_unset=True)
    except AttributeError:
        data = payload.dict(exclude_unset=True)

    # Normalize strings
    if "name" in data and data["name"] is not None:
        data["name"] = data["name"].strip()
        if not data["name"]:
            raise HTTPException(status_code=400, detail="Name cannot be empty")

        # Optional: enforce unique name
        dup = (
            db.query(Discipline)
            .filter(Discipline.name == data["name"], Discipline.discipline_id != discipline_id)
            .first()
        )
        if dup:
            raise HTTPException(status_code=409, detail="Discipline name already exists")

    if "short_code" in data and data["short_code"] is not None:
        data["short_code"] = data["short_code"].strip() or None

    # Apply updates
    for k, v in data.items():
        setattr(disc, k, v)

    db.commit()
    db.refresh(disc)
    return disc


@router.delete("/{discipline_id}", status_code=204)
def delete_discipline(
    discipline_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
    _mfa=Depends(require_mfa_verified),  # <-- add this
):

    disc = db.query(Discipline).filter(Discipline.discipline_id == discipline_id).first()
    if not disc:
        raise HTTPException(status_code=404, detail="Discipline not found")

    # If you have Standards/Certifications pointing to Discipline, deletion may fail due to FK constraints.
    # You can either:
    # - let the DB raise an IntegrityError (and surface a 409), or
    # - explicitly check for related rows if you have relationships configured.
    try:
        db.delete(disc)
        db.commit()
    except Exception as e:
        db.rollback()
        # Most likely FK constraint
        raise HTTPException(
            status_code=409,
            detail="Cannot delete discipline: it is referenced by other records (e.g., standards/certifications).",
        )

    return None
