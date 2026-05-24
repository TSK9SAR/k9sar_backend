from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
from datetime import datetime, timedelta, timezone
from app.utils.auth import require_admin


from app.database import get_db
from app.utils.auth import get_current_user, require_supervisor, require_mfa_verified  # adjust import if needed
from app.models.user import AuthEvent, User
from app.models.role import Role
from app.models.handler import Handler
from sqlalchemy import inspect
from app.models.team import Team
from app.models.dog import Dog
from app.models.handler_affiliations import HandlerAffiliation
from app.models.public_portal_event import PublicPortalEvent
from app.utils.affiliation_scope import require_supervisor_or_admin, scope_users_query
from app.schemas.admin_bundle_schema import AdminUserBundleOut
from app.schemas.admin_user_schema import AdminUserOut, AdminUserListOut, AdminUserPatch, HandlerSummary, AdminUserLoginActivityOut, AdminAuthEventOut

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


def _user_to_out(u: User) -> AdminUserOut:
    roles = u.roles or []
    role_names = sorted([r.role_name for r in roles if r.role_name])
    role_ids = sorted([r.role_id for r in roles if r.role_id is not None])

    handler_summary = None
    if u.handler is not None:
        handler_summary = HandlerSummary(handler_id=u.handler.handler_id, status=u.handler.status)

    return AdminUserOut(
        user_id=u.user_id,
        first_name=u.first_name,
        last_name=u.last_name,
        email=u.email,
        username=u.username,
        phone=u.phone,
        roles=role_names,
        role_ids=role_ids,
        handler=handler_summary,
        created_at=u.created_at,
        updated_at=u.updated_at,
        is_active=getattr(u, "is_active", True),
    )

def _handler_to_dict(h) -> dict:
    u = getattr(h, "user", None)
    return {
        "handler_id": int(h.handler_id),
        "user_id": int(h.user_id),
        "status": h.status,
        "experience_level": h.experience_level,
        "group_affiliation": getattr(h, "group_affiliation", None),  # <-- ADD THIS
        "notes": h.notes,
        "created_at": getattr(h, "created_at", None),
        "updated_at": getattr(h, "updated_at", None),
        "username": getattr(u, "username", None),
        "email": getattr(u, "email", None),
        "first_name": getattr(u, "first_name", None),
        "last_name": getattr(u, "last_name", None),
    }

def utcnow():
    return datetime.now(timezone.utc)

def as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

@router.get("/login-activity", response_model=list[AdminUserLoginActivityOut])
def get_login_activity(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):

    now = datetime.now(timezone.utc)
    active_cutoff = now - timedelta(minutes=15)

    rows = (
        db.query(User)
        .order_by(User.last_name.asc(), User.first_name.asc(), User.user_id.asc())
        .filter(User.is_active == True)
        .all()
    )

    out: list[AdminUserLoginActivityOut] = []
    for u in rows:
        last_seen = as_utc(u.last_seen_at)

        out.append(
            AdminUserLoginActivityOut(
                user_id=u.user_id,
                first_name=u.first_name,
                last_name=u.last_name,
                email=u.email,
                last_login_at=as_utc(u.last_login_at),
                login_count=int(u.login_count or 0),
                last_mfa_verified_at=as_utc(u.last_mfa_verified_at),
                mfa_verify_count=int(u.mfa_verify_count or 0),
                last_seen_at=last_seen,
                active_now=bool(last_seen and last_seen >= active_cutoff),
            )
        )

    return out

@router.get("/{user_id}/login-history", response_model=list[AdminAuthEventOut])
def get_user_login_history(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    user = db.query(User).filter(User.user_id == user_id).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    rows = (
        db.query(AuthEvent)
        .filter(AuthEvent.user_id == user_id)
        .order_by(AuthEvent.occurred_at.desc(), AuthEvent.auth_event_id.desc())
        .limit(100)
        .all()
    )

    out: list[AdminAuthEventOut] = []
    for u in rows:
        u.occurred_at = as_utc(u.occurred_at)
        out.append(AdminAuthEventOut(**u.__dict__))

    return out

@router.get("", response_model=AdminUserListOut)
def admin_list_users(
    q: Optional[str] = Query(default=None, description="Search first/last/email/username"),
    role: Optional[str] = Query(default=None, description="Role name filter (role_name)"),
    handler_status: Optional[str] = Query(default=None, description="Filter users by handler status"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_supervisor_or_admin(db, current_user)

    base = scope_users_query(db.query(User), db, current_user)

    if q and q.strip():
        like = f"%{q.strip()}%"
        base = base.filter(
            or_(
                User.first_name.ilike(like),
                User.last_name.ilike(like),
                User.email.ilike(like),
                User.username.ilike(like),
            )
        )

    if role:
        base = base.join(User.roles).filter(Role.role_name == role)

    if handler_status:
        base = base.join(User.handler).filter(Handler.status == handler_status)

    total = base.distinct(User.user_id).count() if (role or handler_status) else base.count()

    q2 = (
        base.options(joinedload(User.roles), joinedload(User.handler))
        .order_by(User.user_id.desc())
    )
    if role or handler_status:
        q2 = q2.distinct(User.user_id)

    users = q2.offset(skip).limit(limit).all()

    for u in users:
        handler_id = getattr(getattr(u, "handler", None), "handler_id", None)
        aff_rows = []
        if handler_id:
            aff_rows = (
                db.query(HandlerAffiliation.affiliation_id)
                .filter(HandlerAffiliation.handler_id == handler_id)
                .all()
            )
        # print(
        #     "returned user:",
        #     u.user_id,
        #     u.first_name,
        #     u.last_name,
        #     "handler_id=",
        #     handler_id,
        #     "affiliations=",
        #     [r[0] for r in aff_rows],
        # )

    return AdminUserListOut(items=[_user_to_out(u) for u in users], total=total)


@router.get("/{user_id}", response_model=AdminUserOut)
def admin_get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_supervisor_or_admin(db, current_user)

    u = (
        scope_users_query(db.query(User), db, current_user)
        .options(
            joinedload(User.roles),
            joinedload(User.handler)
                .joinedload(Handler.teams)
                .joinedload(Team.dog),
        )
        .filter(User.user_id == user_id)
        .first()
    )

    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    return _user_to_out(u)


@router.patch("/{user_id}", response_model=AdminUserOut)
def admin_patch_user_roles(
    user_id: int,
    payload: AdminUserPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _mfa=Depends(require_mfa_verified),
):
    require_supervisor_or_admin(db, current_user)

    u = (
        scope_users_query(
            db.query(User)
            .options(joinedload(User.roles), joinedload(User.handler))
            .filter(User.user_id == user_id),
            db,
            current_user,
        )
        .first()
    )
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    def _role_names(role_objs) -> set[str]:
        return {
            (getattr(r, "role_name", "") or "").strip().lower()
            for r in (role_objs or [])
        }

    editor_role_names = _role_names(getattr(current_user, "roles", []))
    target_role_names = _role_names(getattr(u, "roles", []))

    editor_is_admin = "admin" in editor_role_names
    editor_is_supervisor = "supervisor" in editor_role_names

    # Supervisors may not modify admin users at all.
    if not editor_is_admin and "admin" in target_role_names:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to modify an admin user",
        )

    changed = False

    if payload.is_active is not None:
        if getattr(current_user, "user_id", None) == user_id and payload.is_active is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot deactivate your own account",
            )

        u.is_active = payload.is_active
        changed = True

    if payload.role_ids is not None:
        requested_ids = sorted(set(payload.role_ids))
        roles: List[Role] = []

        if requested_ids:
            roles = db.query(Role).filter(Role.role_id.in_(requested_ids)).all()
            found_ids = sorted(r.role_id for r in roles)
            if found_ids != requested_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="One or more role_ids are invalid",
                )

        requested_role_names = _role_names(roles)

        if not editor_is_admin:
            # only supervisors should reach here
            if not editor_is_supervisor:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not authorized",
                )

            # Supervisors may never assign admin.
            if "admin" in requested_role_names:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not authorized to assign admin role",
                )

            # Supervisors may only assign peer-or-lower roles.
            allowed_supervisor_roles = {"member", "supervisor"}
            if not requested_role_names.issubset(allowed_supervisor_roles):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not authorized to assign one or more roles",
                )

        # Optional safety: prevent self-demotion for admins if you want
        if getattr(current_user, "user_id", None) == user_id:
            if editor_is_admin and "admin" not in requested_role_names:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="You cannot remove your own admin role",
                )

        u.roles = roles
        changed = True

    if payload.email is not None:
        new_email = payload.email.strip().lower()

        existing = (
            db.query(User)
            .filter(User.email == new_email, User.user_id != u.user_id)
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already in use",
            )

        u.email = new_email
        changed = True

    if changed:
        db.add(u)
        db.commit()
        db.refresh(u)

    return _user_to_out(u)


@router.get("/{user_id}/bundle", response_model=AdminUserBundleOut)
def admin_user_bundle(
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_supervisor),
):
    """
    Admin bundle: user + handler + teams + dogs
    - user: admin users shape (includes roles + handler summary)
    - handler: admin handler shape (includes handler fields + embedded user fields)
    - teams: list
    - dogs: list (attempts via Team.dogs, else via Dog.team_id or Dog.handler_id)
    """

    require_supervisor_or_admin(db, current_user)

    u = (
        scope_users_query(
            db.query(User), db,
            current_user,
        )
        .options(
            joinedload(User.roles),
            joinedload(User.handler)
                .joinedload(Handler.teams)
                .joinedload(Team.dog),
        )
        .filter(User.user_id == user_id)
        .first()
    )

    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    # Reuse your existing serialization helpers if present in this module
    # If you named them differently, adjust here.
    try:
        user_out = _user_to_out(u).dict()
    except Exception:
        # fallback minimal user dict
        user_out = {
            "user_id": u.user_id,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "email": u.email,
            "username": u.username,
        }

    handler_obj = u.handler
    handler_out = None
    teams_out = []
    dogs_out = []

    # Teams
    if handler_obj is not None:
        # Try to reuse your admin handler out helper (if available)
        handler_out = _handler_to_dict(handler_obj)

        teams = handler_obj.teams or []
        for t in teams:
            teams_out.append(_team_to_dict(t))

        # Dogs: prefer relationship Team.dogs if it exists
        dogs_out = _collect_dogs(db, teams)

    return AdminUserBundleOut(
        user=user_out,
        handler=handler_out,
        teams=teams_out,
        dogs=dogs_out,
    )


def _team_to_dict(t: Team) -> dict:
    # Works even if your columns are named slightly differently
    d = {"team_id": int(getattr(t, "team_id"))}
    for k in ["team_name", "name", "title"]:
        if hasattr(t, k):
            d["team_name"] = getattr(t, k)
            break
    if hasattr(t, "status"):
        d["status"] = getattr(t, "status")
    return d


def _dog_to_dict(dog: Dog) -> dict:
    d = {"dog_id": int(getattr(dog, "dog_id"))}
    for k in ["dog_name", "name", "call_name"]:
        if hasattr(dog, k):
            d["dog_name"] = getattr(dog, k)
            break
    if hasattr(dog, "status"):
        d["status"] = getattr(dog, "status")
    return d

from sqlalchemy import inspect as sa_inspect, text

def _collect_dogs(db: Session, teams: list[Team]) -> list[dict]:
    out: list[dict] = []
    seen: set[int] = set()

    # 1) Prefer already-loaded relationship Team.dog
    for t in teams or []:
        dog = getattr(t, "dog", None)
        if dog is None:
            continue
        dog_id = int(dog.dog_id)
        if dog_id in seen:
            continue
        seen.add(dog_id)
        out.append(_dog_to_dict(dog))

    if out:
        return out

    # 2) Fallback: query by teams.dog_id
    dog_ids = []
    for t in teams or []:
        did = getattr(t, "dog_id", None)
        if did is not None:
            dog_ids.append(int(did))

    dog_ids = sorted(set(dog_ids))
    if not dog_ids:
        return []

    dogs = db.query(Dog).filter(Dog.dog_id.in_(dog_ids)).all()
    for dog in dogs:
        dog_id = int(dog.dog_id)
        if dog_id in seen:
            continue
        seen.add(dog_id)
        out.append(_dog_to_dict(dog))

    return out

from datetime import datetime, timedelta, timezone
from sqlalchemy import or_

@router.get("/activity/public")
def list_public_portal_activity(
    section: str | None = None,
    q: str | None = None,
    days: int = 30,
    limit: int = 200,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):

    cutoff = datetime.utcnow() - timedelta(days=days)

    query = db.query(PublicPortalEvent).filter(
        PublicPortalEvent.occurred_at >= cutoff
    )

    if section:
        query = query.filter(PublicPortalEvent.section == section)

    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                PublicPortalEvent.ip_address.ilike(like),
                PublicPortalEvent.referer.ilike(like),
                PublicPortalEvent.session_id.ilike(like),
                PublicPortalEvent.section.ilike(like),
            )
        )

    rows = (
        query.order_by(PublicPortalEvent.occurred_at.desc())
        .limit(min(limit, 500))
        .all()
    )

    result = []
    for r in rows:
        occurred_at = r.occurred_at
        if occurred_at and occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)

        result.append(
            {
                "event_id": r.event_id,
                "occurred_at": occurred_at,
                "section": r.section,
                "session_id": r.session_id,
                "ip_address": r.ip_address,
                "user_agent": r.user_agent,
                "referer": r.referer,
            }
        )

    return result