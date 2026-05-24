# app/routes/handler_routes.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.models.handler import Handler


from app.schemas.handler_schema import HandlerCreate, HandlerUpdate, HandlerOut, HandlerEnsureOut
from app.utils.auth import get_current_user, require_admin, require_supervisor

from sqlalchemy.exc import IntegrityError


from app.database import get_db

from app.utils.affiliation_scope import get_affiliation_scope
from app import models


from app.utils.auth import user_has_role

router = APIRouter(prefix="/handlers", tags=["Handlers"])


@router.post("/", response_model=HandlerOut)
def create_handler(
    payload: HandlerCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_supervisor),
):
    # Decide who this handler is for:
    target_user_id = current_user.user_id

    # Allow elevated roles to create for someone else
    if payload.user_id is not None:
        target_user_id = payload.user_id

    # Prevent duplicate handler records (1-to-1 relationship)
    existing = (
        db.query(models.Handler)
        .filter(models.Handler.user_id == target_user_id)
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already has a handler profile.",
        )

    handler = models.Handler(
        user_id=target_user_id,
        experience_level=payload.experience_level,
        status=payload.status,
        notes=payload.notes,
    )

    db.add(handler)
    db.commit()
    db.refresh(handler)

    return handler


@router.get("/", response_model=List[HandlerOut])
def get_all_handlers(db: Session = Depends(get_db)):
    return db.query(Handler).all()

@router.get("/{handler_id}/neighbors")
def handler_neighbors(
    handler_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):

    # ensure exists
    exists = db.query(Handler.handler_id).filter(Handler.handler_id == handler_id).first()
    if not exists:
        raise HTTPException(status_code=404, detail="Handler not found")

    prev_id = (
        db.query(Handler.handler_id)
        .filter(Handler.handler_id < handler_id)
        .order_by(Handler.handler_id.desc())
        .limit(1)
        .scalar()
    )
    next_id = (
        db.query(Handler.handler_id)
        .filter(Handler.handler_id > handler_id)
        .order_by(Handler.handler_id.asc())
        .limit(1)
        .scalar()
    )

    return {"prev_id": prev_id, "next_id": next_id}

@router.get("/{handler_id}", response_model=HandlerOut)
def get_handler(handler_id: int, db: Session = Depends(get_db)):
    handler = db.query(Handler).filter(Handler.handler_id == handler_id).first()
    if not handler:
        raise HTTPException(status_code=404, detail="Handler not found")
    return handler


@router.put("/{handler_id}", response_model=HandlerOut)
def update_handler(handler_id: int, updates: HandlerUpdate, db: Session = Depends(get_db)):
    handler = db.query(Handler).filter(Handler.handler_id == handler_id).first()
    if not handler:
        raise HTTPException(status_code=404, detail="Handler not found")

    for key, value in updates.model_dump(exclude_unset=True).items():
        setattr(handler, key, value)

    db.commit()
    db.refresh(handler)
    return handler


@router.delete("/{handler_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_handler(handler_id: int, db: Session = Depends(get_db)):
    handler = db.query(Handler).filter(Handler.handler_id == handler_id).first()
    if not handler:
        raise HTTPException(status_code=404, detail="Handler not found")

    db.delete(handler)
    db.commit()
    return {"detail": "Handler deleted"}


@router.post("/ensure", response_model=HandlerEnsureOut)
def ensure_handler(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # 1) Return existing if present
    existing = (
        db.query(Handler)
        .filter(Handler.user_id == current_user.user_id)
        .first()
    )
    if existing:
        return HandlerEnsureOut(handler_id=existing.handler_id, created=False)

    # 2) Create new (idempotent under concurrency)
    h = Handler(
        user_id=current_user.user_id,
        # Optional defaults:
        status="active",
        experience_level=None,
        notes=None,
    )

    db.add(h)
    try:
        db.commit()
        db.refresh(h)
        return HandlerEnsureOut(handler_id=h.handler_id, created=True)
    except IntegrityError:
        # Another request created it first (unique constraint hit)
        db.rollback()
        existing2 = (
            db.query(Handler)
            .filter(Handler.user_id == current_user.user_id)
            .first()
        )
        if not existing2:
            raise HTTPException(status_code=500, detail="Failed to ensure handler.")
        return HandlerEnsureOut(handler_id=existing2.handler_id, created=False)


