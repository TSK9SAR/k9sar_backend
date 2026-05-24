# app/utils/auth.py

import os
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import exists, select
from app.models.user_discipline_group import user_discipline_groups # adjust import/name
from app.services.auth_activity import touch_last_seen
from jose.exceptions import ExpiredSignatureError

from app.models.certification import Certification
from app.models.team import Team
from app.models.handler import Handler
from datetime import datetime, timezone, timedelta

from app.utils.authz import has_role_db
from app.database import get_db
from app.models.user import User  # adjust path/name if needed
from app.utils.jwt_handler import verify_access_token, decode_access_token
from app.models.user_roles import user_roles
from app.models.standard import Standard
from enum import IntEnum

# TODO: load from env/config in real deployment
SECRET_KEY=os.getenv("JWT_SECRET")
ALGORITHM=os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
REFRESH_TOKEN_EXPIRE_DAYS=os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7")
RESET_TOKEN_TTL_MINUTES=os.getenv("RESET_TOKEN_TTL_MINUTES", "60")
INVITE_TOKEN_TTL_DAYS=os.getenv("INVITE_TOKEN_TTL_DAYS", "7")

# This must point to one of your login/token endpoints
# I suggest we standardize on /auth/login for now:
#oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

def user_has_role(user, role_name: str) -> bool:
    roles = getattr(user, "roles", None) or []
    return any(
        (getattr(r, "role_name", "") or "").lower() == role_name.lower()
        for r in roles
    )


def is_evaluator(db: Session, user_id: int) -> bool:
    stmt = (
        select(user_discipline_groups.c.user_id)
        .where(user_discipline_groups.c.user_id == user_id)
        .limit(1)
    )
    return db.execute(stmt).first() is not None

def requires_2fa(db: Session, user) -> bool:
    # evaluator == exists in user_discipline_groups
    return is_evaluator(db, user.user_id)

def can_manage_signature(db: Session, user) -> bool:
    uid = user.user_id
    return has_role_db(db, uid, "admin") or is_evaluator(db, uid)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated: missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated: invalid/expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    sub = payload.get("sub")
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated: token missing sub",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = int(sub)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated: token sub not int",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.is_active == True).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated: user not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    touch_last_seen(db, user=user, threshold_minutes=3, commit=True)

    return user


def get_token_payload(token: str = Depends(oauth2_scheme)) -> dict:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated: missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated: invalid/expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


def _payload_shows_mfa_verified(payload: dict) -> bool:
    # Accept a few common patterns; use whichever you actually issue
    if payload.get("mfa_verified") is True:
        return True
    if payload.get("mfa") is True:
        return True
    amr = payload.get("amr")
    if isinstance(amr, list) and any(x in ("mfa", "otp", "totp") for x in amr):
        return True
    return False


def get_current_user_no_mfa(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_access_token(token)
    except (ExpiredSignatureError, JWTError, Exception):
        raise credentials_exc

    if not payload:
        raise credentials_exc

    user_id = payload.get("sub") or payload.get("user_id")
    if not user_id:
        raise credentials_exc

    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        raise credentials_exc

    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise credentials_exc

    return user

def get_jwt_claims(request: Request) -> dict:
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization bearer token")

    token = auth.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")

    decoded = verify_access_token(token)
    if not decoded:
        raise HTTPException(status_code=401, detail="Invalid token")

    return decoded


def require_mfa_verified(claims: dict = Depends(get_jwt_claims)):
    if claims.get("typ") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")

    if claims.get("mfa_verified") is not True:
        raise HTTPException(
            status_code=403,
            detail="2FA verification is required for this action.",
        )

    method = claims.get("mfa_method")
    if method is not None and method not in {"totp", "passkey"}:
        raise HTTPException(
            status_code=403,
            detail="Approved MFA method required",
        )

    return True


def require_mfa_for_evaluator_actions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    claims: dict = Depends(get_jwt_claims),
):
    if not requires_2fa(db, current_user):
        return

    if claims.get("typ") != "access" or claims.get("mfa_verified") is not True:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "MFA_REQUIRED_FOR_ISSUING",
                "message": "2FA verification is required to issue certifications.",
                "action": "prompt_mfa_verify",
            },
        )

REAUTH_TTL_MINUTES = 10

def _payload_shows_recent_reauth(payload: dict) -> bool:
    if payload.get("reauth_verified") is not True:
        return False

    reauth_at = payload.get("reauth_at")
    if not reauth_at:
        return False

    try:
        reauth_dt = datetime.fromtimestamp(int(reauth_at), tz=timezone.utc)
    except Exception:
        return False

    return datetime.now(timezone.utc) - reauth_dt <= timedelta(minutes=REAUTH_TTL_MINUTES)

def require_recent_reauth(claims: dict = Depends(get_jwt_claims)):
    if claims.get("typ") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")

    if not _payload_shows_recent_reauth(claims):
        raise HTTPException(
            status_code=403,
            detail="Recent re-authentication required",
        )

    return True

class RoleId(IntEnum):
    MEMBER = 1
    SUPERVISOR = 2
    ADMIN = 3

def require_supervisor(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Allow Supervisor or Admin based on role_id enum values.
    Does NOT rely on ORM relationship loading.
    """

    user_id = getattr(current_user, "user_id", None) or getattr(current_user, "id", None)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    rows = (
        db.query(user_roles.c.role_id)
        .filter(user_roles.c.user_id == int(user_id))
        .all()
    )
    role_ids = {int(r[0]) for r in rows}

    allowed = {int(RoleId.SUPERVISOR), int(RoleId.ADMIN)}
    if role_ids & allowed:
        return current_user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Supervisor or administrator privileges required",
    )

def require_admin(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Allow Admin based on role_id enum values.
    Does NOT rely on ORM relationship loading.
    """

    user_id = getattr(current_user, "user_id", None) or getattr(current_user, "id", None)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    rows = (
        db.query(user_roles.c.role_id)
        .filter(user_roles.c.user_id == int(user_id))
        .all()
    )
    role_ids = {int(r[0]) for r in rows}

    allowed = {int(RoleId.ADMIN)}
    if role_ids & allowed:
        return current_user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Administrator privileges required",
    )

def current_user_id(current_user) -> int:
    # int (some auth deps return user_id directly)
    if isinstance(current_user, int):
        return current_user

    # dict / token payload style
    if isinstance(current_user, dict):
        for k in ("user_id", "id", "sub"):
            v = current_user.get(k)
            if isinstance(v, int):
                return v
            if isinstance(v, str) and v.isdigit():
                return int(v)

    # object / ORM model style
    for attr in ("user_id", "id"):
        v = getattr(current_user, attr, None)
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.isdigit():
            return int(v)

    raise HTTPException(status_code=401, detail="Invalid auth context: missing user id")



def can_view_certificate(db: Session, current_user: User, cert: Certification) -> bool:
    # Admin role
    if user_has_role(current_user, "admin"):
        return True

    cu_id = getattr(current_user, "user_id", None)
    if cu_id is None:
        return False

    # Explicit owner column, if present
    owner_id = getattr(cert, "owner_user_id", None)
    if owner_id is not None and int(owner_id) == int(cu_id):
        return True

    # Primary evaluator
    sup_id = getattr(cert, "supervisor_id", None)
    if sup_id is not None and int(sup_id) == int(cu_id):
        return True

    # Co-evaluator
    co_id = getattr(cert, "co_evaluator_user_id", None)
    if co_id is not None and int(co_id) == int(cu_id):
        return True

    # Owner via team -> handler -> user_id
    team_id = getattr(cert, "team_id", None)
    if team_id is not None:
        team = db.query(Team).filter(Team.team_id == team_id).first()
        if team and getattr(team, "handler_id", None):
            handler = db.query(Handler).filter(Handler.handler_id == team.handler_id).first()
            if handler and getattr(handler, "user_id", None) is not None:
                if int(handler.user_id) == int(cu_id):
                    return True

    # Evaluator via discipline group
    std_id = getattr(cert, "standard_id", None)
    if std_id is not None:
        std = db.query(Standard).filter(Standard.standard_id == std_id).first()
        disc = getattr(std, "discipline", None) if std else None
        group_id = getattr(disc, "group_id", None) if disc else None

        raw_groups = getattr(current_user, "discipline_groups", []) or []
        user_group_ids = set()
        for g in raw_groups:
            try:
                gid = g.get("group_id") if isinstance(g, dict) else getattr(g, "group_id", None)
                if gid is not None:
                    user_group_ids.add(int(gid))
            except Exception:
                pass

        if group_id is not None and int(group_id) in user_group_ids:
            return True

    return False

