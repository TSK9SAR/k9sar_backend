from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select
from typing import List

from app.database import get_db
from app.models.user import User
from app.models.role import Role
from app.models.user_roles import user_roles
from app.utils.auth import get_current_user, get_token_payload, _payload_shows_mfa_verified, require_admin, require_supervisor

from app.schemas.user_schema import UserUpdate, UserOut, UserMeUpdate
from app.schemas.user_roles_schema import UserRolesUpdate

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", response_model=UserOut)
def get_me(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    payload: dict = Depends(get_token_payload),
):
    # Load a fresh instance (and eager-load discipline_groups if needed)
    user = (
        db.query(User)
        .options(joinedload(User.discipline_groups))  # only if relationship exists
        .filter(User.user_id == current_user.user_id)                                                   
        .first()
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Roles -> list[str]
    role_names = (
        db.execute(
            select(Role.role_name)
            .select_from(user_roles.join(Role, user_roles.c.role_id == Role.role_id))
            .where(user_roles.c.user_id == user.user_id)
        )
        .scalars()
        .all()
    )
    roles: List[str] = [r for r in role_names if r]

    # Evaluator = has any discipline groups
    discipline_groups = getattr(user, "discipline_groups", None) or []
    is_evaluator = bool(discipline_groups)

    # Handler flag: depends on your linkage.
    # If you have User.handler relationship:
    is_handler = getattr(user, "handler", None) is not None

    # If you instead link Handler -> User via handlers.user_id (no relationship),
    # replace the line above with a DB check against Handler.
    # (Tell me if that's your case and I'll drop in the exact query.)

    # 2FA verified = token/session state
    is_2fa_verified = bool(_payload_shows_mfa_verified(payload))

    # Return explicit schema so computed fields are included
    return UserOut(
        user_id=user.user_id,
        username=user.username,
        email=user.email,
        roles=roles,
        is_handler=is_handler,        # matches your schema spelling
        is_evaluator=is_evaluator,
        is_2fa_verified=is_2fa_verified,
        discipline_groups=discipline_groups,
        is_active=bool(user.is_active),
        signature_url=getattr(user, "signature_url", None),
        signature_hash=getattr(user, "signature_hash", None),
        signature_updated_at=getattr(user, "signature_updated_at", None),
    )


@router.get("/info")
def get_user_info(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    display_name = f"{current_user.first_name} {current_user.last_name}".strip() or current_user.email
    return {
        "user_id": current_user.user_id,
        "email": current_user.email,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "display_name": display_name,
    }



@router.get("/{user_id}", response_model=UserOut)
def get_user_by_id_route(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Only supervisors/admins can fetch arbitrary users (keep your policy)
    role_names = {r.role_name for r in (current_user.roles or [])}
    if not (("admin" in role_names) or ("supervisor" in role_names)):
        raise HTTPException(status_code=403, detail="Not authorized")

    user = db.query(User).filter(User.user_id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.put("/me", response_model=UserOut)
def update_user_profile_put(
    update: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Full update (legacy). If you don't need PUT, you can remove it later.
    """
    user = db.query(User).filter(User.user_id == current_user.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Recommended: only admins can deactivate/reactivate
    if user.is_active is not None:
        require_admin(db, current_user)   # whatever your admin check is
        user.is_active = bool(user.is_active)
        
    # Pydantic v1 uses .dict, v2 uses .model_dump
    data = update.dict(exclude_unset=True) if hasattr(update, "dict") else update.model_dump(exclude_unset=True)

    for field, value in data.items():
        setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return user


@router.patch("/me", response_model=UserOut)
def update_me_patch(
    payload: UserMeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Partial update for "My Profile" page.
    """
    user = db.query(User).filter(User.user_id == current_user.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    data = payload.dict(exclude_unset=True) if hasattr(payload, "dict") else payload.model_dump(exclude_unset=True)

    for field, value in data.items():
        setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}/roles")
def update_user_roles(
    user_id: int,
    payload: UserRolesUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):

    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    requested = [r.strip().lower() for r in payload.role_names if r and r.strip()]
    requested = list(dict.fromkeys(requested))  # de-dupe

    if not requested:
        raise HTTPException(status_code=400, detail="At least one role is required")

    actor_roles = {r.role_name for r in (current_user.roles or [])}
    actor_is_admin = "admin" in actor_roles

    target_current_roles = {r.role_name for r in (user.roles or [])}

    if "admin" in requested and not actor_is_admin:
        raise HTTPException(status_code=403, detail="Only admin can grant admin role")

    if user.user_id == current_user.user_id:
        if "admin" in target_current_roles and "admin" not in requested:
            raise HTTPException(status_code=400, detail="You cannot remove your own admin role")
        if (not actor_is_admin) and ("supervisor" in target_current_roles) and ("supervisor" not in requested):
            raise HTTPException(status_code=400, detail="You cannot remove your own supervisor role")

    if "admin" in target_current_roles and "admin" not in requested:
        other_admin_count = (
            db.query(User)
            .join(User.roles)
            .filter(Role.role_name == "admin")
            .filter(User.user_id != user.user_id)
            .distinct()
            .count()
        )
        if other_admin_count == 0:
            raise HTTPException(status_code=400, detail="Cannot remove the last admin")

    roles = db.query(Role).filter(Role.role_name.in_(requested)).all()
    found = {r.role_name for r in roles}
    missing = [r for r in requested if r not in found]
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown role(s): {missing}")

    user.roles = roles
    db.commit()
    db.refresh(user)

    return {
        "user_id": user.user_id,
        "username": user.username,
        "roles": [r.role_name for r in user.roles],
    }

