from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import user
from app.models.discipline import Discipline
from app.models.standard import Standard
from app.models.team import Team
from app.models.handler import Handler
from app.models.role import Role
from app.models.user_roles import user_roles  # this is a SQLAlchemy Table
from app.models.user_discipline_group import user_discipline_groups
from app.models.user import User
from app.utils.affiliation_scope import get_affiliation_scope
from app.models.webauthn_credential import WebAuthnCredential


# -------------------------
# Roles / authorization core
# -------------------------

def has_role_db(db: Session, user_id: int, *names: str) -> bool:
    """
    DB-backed role check using user_roles join table.
    Works even if user.roles relationship is not loaded.
    """
    wanted = {n.lower() for n in names}

    stmt = (
        select(Role.role_name)
        .select_from(user_roles.join(Role, user_roles.c.role_id == Role.role_id))
        .where(user_roles.c.user_id == user_id)
    )
    role_names = db.execute(stmt).scalars().all()
    return any((rn or "").lower() in wanted for rn in role_names)


def has_role(user, *names: str) -> bool:
    """
    In-memory role check against user.roles if present.
    Falls back gracefully if roles aren't loaded.
    """
    wanted = {n.lower() for n in names}
    roles = getattr(user, "roles", None) or []
    return any(((getattr(r, "role_name", "") or "").lower() in wanted) for r in roles)


# def require_admin(user) -> None:
#     if not has_role(user, "admin"):
#         raise HTTPException(status_code=403, detail="Administrator role required")


def require_member(user) -> None:
    # Must be at least member/supervisor/admin
    if not has_role(user, "admin", "supervisor", "member"):
        raise HTTPException(status_code=403, detail="Member role required")


def require_supervisor_or_admin_db(db: Session, user_id: int) -> None:
    if has_role_db(db, user_id, "admin", "supervisor"):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Supervisor or admin required")


def require_self_or_elevated(user, target_user_id: int) -> None:
    if getattr(user, "user_id", None) != target_user_id and not has_role(user, "admin", "supervisor"):
        raise HTTPException(status_code=403, detail="Not authorized")
    
def require_supervisor_or_admin(*args) -> None:
    """
    Backward-compatible wrapper.

    Supports:
      - require_supervisor_or_admin(user)
      - require_supervisor_or_admin(db, user)

    Prefer require_supervisor_or_admin_db(db, user_id) in new code.
    """
    if len(args) == 1:
        user = args[0]
        if not has_role(user, "admin", "supervisor"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Supervisor or admin required")
        return

    if len(args) == 2:
        db, user = args
        uid = getattr(user, "user_id", None) or getattr(user, "id", None)
        if uid is None:
            raise HTTPException(status_code=400, detail="Authenticated user missing user_id")
        require_supervisor_or_admin_db(db, int(uid))
        return

    raise TypeError("require_supervisor_or_admin expects (user) or (db, user)")


def can_manage_members(user) -> bool:
    return has_role(user, "admin", "supervisor")


def can_manage_teams(user) -> bool:
    return has_role(user, "admin", "supervisor")


def can_manage_admin_only(user) -> bool:
    return has_role(user, "admin")


# -------------------------
# Evaluator checks (unchanged behavior)
# -------------------------

def require_evaluator_for_discipline(user, discipline_id: int, db: Session):
    # must be evaluator
    if not getattr(user, "discipline_groups", None):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Evaluator privileges required",
        )

    disc = db.query(Discipline).filter(Discipline.discipline_id == discipline_id).first()
    if not disc:
        raise HTTPException(status_code=404, detail="Discipline not found")

    allowed_group_ids = {g.group_id for g in user.discipline_groups}
    if disc.group_id not in allowed_group_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized for this discipline",
        )
    return disc


def require_evaluator_for_cert(current_user, cert, db: Session):
    if not cert or not getattr(cert, "standard_id", None):
        raise HTTPException(status_code=400, detail="Certification missing standard_id")

    discipline_id = (
        db.query(Standard.discipline_id)
        .filter(Standard.standard_id == cert.standard_id)
        .scalar()
    )
    if not discipline_id:
        raise HTTPException(status_code=400, detail="Could not resolve discipline for certification")

    require_evaluator_for_discipline(current_user, int(discipline_id), db)


def require_evaluator_for_standard(user, standard_id: int, db: Session):
    if not getattr(user, "discipline_groups", None) or len(user.discipline_groups) == 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Evaluator privileges required",
        )

    std = db.query(Standard).filter(Standard.standard_id == standard_id).first()
    if not std:
        raise HTTPException(status_code=404, detail="Standard not found")

    disc = getattr(std, "discipline", None)
    if disc is None:
        disc = db.query(Discipline).filter(Discipline.discipline_id == std.discipline_id).first()

    if not disc:
        raise HTTPException(status_code=404, detail="Discipline not found for standard")

    allowed_group_ids = {g.group_id for g in user.discipline_groups}
    if disc.group_id not in allowed_group_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized for this standard/discipline",
        )
    return std


def get_allowed_standard_ids(db: Session, user_id: int) -> list[int]:
    q = (
        db.query(Standard.standard_id)
        .join(Discipline, Discipline.discipline_id == Standard.discipline_id)
        .join(user_discipline_groups, user_discipline_groups.c.group_id == Discipline.group_id)
        .filter(user_discipline_groups.c.user_id == user_id)
        .distinct()
    )
    return [row[0] for row in q.all()]


# -------------------------
# Self-certification guard (keep your logic, but make admin check consistent)
# -------------------------

def _user_is_admin(user) -> bool:
    # Prefer roles relationship if present; otherwise fall back to legacy is_admin flags
    if has_role(user, "admin"):
        return True
    return bool(getattr(user, "is_admin", False))


def forbid_self_certification(db: Session, current_user, team_id: int) -> None:
    """
    Prevent evaluators from issuing/modifying certs tied to themselves (admin exempt).
    Rule: if current_user is the handler that owns the team => forbidden.
    """
    if _user_is_admin(current_user):
        return

    uid = getattr(current_user, "user_id", None) or getattr(current_user, "id", None)
    if uid is None:
        raise HTTPException(status_code=400, detail="Authenticated user missing user_id")

    team = db.query(Team).filter(Team.team_id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    handler_id = getattr(team, "handler_id", None)
    if not handler_id:
        return

    handler = db.query(Handler).filter(Handler.handler_id == handler_id).first()
    if not handler:
        return

    handler_user_id = getattr(handler, "user_id", None)
    if handler_user_id and int(handler_user_id) == int(uid):
        raise HTTPException(
            status_code=403,
            detail="Evaluators may not issue or modify certifications tied to themselves.",
        )

def require_can_manage_affiliation(
    db: Session,
    current_user: User,
    affiliation_id: int,
) -> None:
    scope = get_affiliation_scope(db, current_user)

    # admin
    if scope is None:
        return

    # supervisor with no scope or out of scope
    if not scope or affiliation_id not in scope:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to manage this affiliation",
        )


def get_user_mfa_methods(db: Session, user: User) -> dict:
    passkey_count = (
        db.query(WebAuthnCredential)
        .filter(WebAuthnCredential.user_id == user.user_id)
        .count()
    )

    totp_enabled = bool(
        getattr(user, "twofa_enabled", False)
        and getattr(user, "twofa_confirmed", False)
    )

    return {
        "totp_enabled": totp_enabled,
        "passkey_enabled": passkey_count > 0,
        "passkey_count": passkey_count,
    }


def user_has_any_mfa(db: Session, user: User) -> bool:
    m = get_user_mfa_methods(db, user)
    return m["totp_enabled"] or m["passkey_enabled"]


def requires_mfa(user: User) -> bool:
    """
    Central policy: who MUST perform MFA to proceed.

    Adjust this based on your system rules.
    """
    # Example:
    if getattr(user, "is_admin", False):
        return True

    # evaluators (based on your discipline groups logic)
    if getattr(user, "is_evaluator", False):
        return True

    return False