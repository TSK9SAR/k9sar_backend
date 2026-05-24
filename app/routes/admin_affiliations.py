from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.utils.auth import get_current_user, require_mfa_verified, require_admin

from app.models.handler import Affiliation, Handler
from app.schemas.affiliation_schema import (
    AffiliationCreate,
    AffiliationUpdate,
    AffiliationOut,
)
from app.models.user import User
from app.models.handler_affiliations import HandlerAffiliation

router = APIRouter(prefix="/admin/affiliations", tags=["admin-affiliations"])


def _trim_or_none(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    t = s.strip()
    return t if t else None


def is_admin(user: User) -> bool:
    role_names = {r.role_name for r in getattr(user, "roles", [])}
    return getattr(user, "is_admin", False) or "admin" in role_names


def is_supervisor(user: User) -> bool:
    role_names = {r.role_name for r in getattr(user, "roles", [])}
    return "supervisor" in role_names


def get_handler_id_for_user(db: Session, user_id: int) -> int | None:
    handler = (
        db.query(Handler)
        .filter(Handler.user_id == user_id)
        .first()
    )
    return handler.handler_id if handler else None


def get_active_affiliation_ids_for_handler(db: Session, handler_id: int) -> List[int]:
    rows = (
        db.query(HandlerAffiliation.affiliation_id)
        .filter(
            HandlerAffiliation.handler_id == handler_id,
            HandlerAffiliation.ended_at.is_(None),
        )
        .all()
    )
    return [row[0] for row in rows]


def get_manageable_affiliation_ids(db: Session, current_user: User) -> List[int]:
    if is_admin(current_user):
        rows = db.query(Affiliation.affiliation_id).all()
        return [r[0] for r in rows]

    if not is_supervisor(current_user):
        return []

    handler_id = get_handler_id_for_user(db, current_user.user_id)
    if not handler_id:
        return []

    return get_active_affiliation_ids_for_handler(db, handler_id)


def require_admin_or_supervisor(current_user: User) -> None:
    if is_admin(current_user) or is_supervisor(current_user):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not authorized",
    )


def require_can_manage_affiliation(
    db: Session,
    current_user: User,
    affiliation_id: int,
) -> None:
    if is_admin(current_user):
        return

    manageable_ids = set(get_manageable_affiliation_ids(db, current_user))
    if affiliation_id not in manageable_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to manage this affiliation",
        )


@router.get("", response_model=list[AffiliationOut])
def list_affiliations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin_or_supervisor(current_user)

    manageable_ids = get_manageable_affiliation_ids(db, current_user)
    if not manageable_ids:
        return []

    rows = (
        db.query(Affiliation)
        .filter(Affiliation.affiliation_id.in_(manageable_ids))
        .order_by(Affiliation.sortorder.asc(), Affiliation.name.asc())
        .all()
    )
    return rows


@router.post("", response_model=AffiliationOut, status_code=status.HTTP_201_CREATED)
def create_affiliation(
    payload: AffiliationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    _mfa=Depends(require_mfa_verified),
):

    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")

    exists = (
        db.query(Affiliation)
        .filter(Affiliation.name == name)
        .first()
    )
    if exists:
        raise HTTPException(status_code=409, detail="Affiliation name already exists")

    a = Affiliation(
        name=name,
        callout_line=_trim_or_none(payload.callout_line),
        contact_name=_trim_or_none(payload.contact_name),
        phone=_trim_or_none(payload.phone),
        location=_trim_or_none(payload.location),
        url=_trim_or_none(payload.url),
        sortorder=payload.sortorder,
        is_active=True if payload.is_active is None else bool(payload.is_active),
    )

    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@router.put("/{affiliation_id}", response_model=AffiliationOut)
def update_affiliation(
    affiliation_id: int,
    payload: AffiliationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _mfa=Depends(require_mfa_verified),
):
    require_admin_or_supervisor(current_user)
    require_can_manage_affiliation(db, current_user, affiliation_id)

    a = (
        db.query(Affiliation)
        .filter(Affiliation.affiliation_id == affiliation_id)
        .first()
    )
    if not a:
        raise HTTPException(status_code=404, detail="Affiliation not found")

    if payload.name is not None:
        name = (payload.name or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="name cannot be blank")

        dup = (
            db.query(Affiliation)
            .filter(
                Affiliation.name == name,
                Affiliation.affiliation_id != affiliation_id,
            )
            .first()
        )
        if dup:
            raise HTTPException(status_code=409, detail="Affiliation name already exists")
        a.name = name

    if payload.callout_line is not None:
        a.callout_line = _trim_or_none(payload.callout_line)
    if payload.contact_name is not None:
        a.contact_name = _trim_or_none(payload.contact_name)
    if payload.phone is not None:
        a.phone = _trim_or_none(payload.phone)
    if payload.location is not None:
        a.location = _trim_or_none(payload.location)
    if payload.url is not None:
        a.url = _trim_or_none(payload.url)

    if payload.sortorder is not None:
        a.sortorder = payload.sortorder
    if payload.is_active is not None:
        a.is_active = bool(payload.is_active)

    db.commit()
    db.refresh(a)
    return a


@router.delete("/{affiliation_id}")
def delete_affiliation(
    affiliation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    _mfa=Depends(require_mfa_verified),
):

    a = (
        db.query(Affiliation)
        .filter(Affiliation.affiliation_id == affiliation_id)
        .first()
    )
    if not a:
        raise HTTPException(status_code=404, detail="Affiliation not found")

    db.delete(a)
    db.commit()
    return {"ok": True}