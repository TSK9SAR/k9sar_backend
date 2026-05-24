# app/routes/auth_routes.py
from datetime import timedelta, datetime, timezone, time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app import models
from app.database import get_db
from app.models import user
from app.models.user import User
from app.services.auth_activity import mark_login_success
from app.utils.jwt_handler import create_access_token, verify_password
from app.utils.auth import get_current_user, requires_2fa, _payload_shows_mfa_verified, get_token_payload, get_jwt_claims
from app.utils.authz import get_allowed_standard_ids
from app.utils.hashing import hash_password
from app.utils.authz import get_user_mfa_methods, requires_mfa
from app.models.webauthn_credential import WebAuthnCredential
from app.schemas.auth_schema import ReauthPasswordIn
from fastapi import Request
from app.services.auth_activity import _log_event


router = APIRouter(prefix="/auth", tags=["Authentication"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class RegisterRequest(BaseModel):
    # required auth stuff
    username: str
    email: str
    password: str

    # personal details (optional)
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None

    # address / contact fields (optional)
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state_province: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    domicile_lat: float | None = None
    domicile_lng: float | None = None

import io
import base64
import pyotp
import qrcode

from fastapi import Response


def _has_role(user: User, *names: str) -> bool:
    want = {n.lower() for n in names}
    return any((r.role_name or "").lower() in want for r in (user.roles or []))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def authenticate_user(db: Session, ident: str, password: str) -> Optional[User]:
    """
    Allow login via username OR email.
    Eager-load roles so requires_2fa(user) can work reliably.
    """
    user: Optional[User] = (
        db.query(User)
        .options(joinedload(User.roles))
        .filter(or_(User.username == ident, User.email == ident))
        .filter(User.is_active == True)
        .first()
    )
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


@router.post("/logout")
def logout(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    current_user.last_seen_at = None
    db.add(current_user)

    # optional audit event if you want it
    # _log_event(
    #     db,
    #     user_id=current_user.user_id,
    #     event_type="logout",
    #     success=True,
    # )

    db.commit()
    return {"ok": True}


@router.post("/login")
def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    mark_login_success(db, user=user, request=request, commit=False)

    mfa = get_user_mfa_methods(db, user)

    # keep your existing authoritative policy gate
    needs_mfa = bool(requires_2fa(db, user))

    # Decide login follow-up
    if needs_mfa:
        if mfa["totp_enabled"] or mfa["passkey_enabled"]:
            mfa_mode = "verify"
        else:
            mfa_mode = "enroll"
    else:
        mfa_mode = "none"

    # normal access token, same as before
    access_token = create_access_token(
        user.user_id,
        mfa_verified=False,
        expires_minutes=120,
        extra={"typ": "access"},
    )

    resp = {
        "access_token": access_token,
        "token_type": "bearer",
        "requires_2fa": (mfa_mode != "none"),
        "twofa_mode": mfa_mode,  # "verify" | "enroll" | "none"
        "mfa_methods": {
            "totp": mfa["totp_enabled"],
            "passkey": mfa["passkey_enabled"],
        },
    }

    if mfa_mode in ("verify", "enroll"):
        twofa_token = create_access_token(
            user.user_id,
            expires_minutes=5,
            mfa_verified=False,
            extra={"typ": "2fa"},
        )
        resp["twofa_token"] = twofa_token

        db.commit()
        db.refresh(user)

    return resp


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register_user(payload: RegisterRequest, db: Session = Depends(get_db)):
    # 1) Check if username or email already exists
    existing_user = (
        db.query(models.User)
        .filter(or_(models.User.username == payload.username, models.User.email == payload.email))
        .first()
    )
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already registered.",
        )

    # 2) Create the user
    new_user = User(
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=payload.email,
        username=payload.username,
        password_hash=hash_password(payload.password),
        phone=payload.phone,
        address_line1=payload.address_line1,
        address_line2=payload.address_line2,
        city=payload.city,
        state_province=payload.state_province,
        postal_code=payload.postal_code,
        country=payload.country,
        domicile_lat=payload.domicile_lat,
        domicile_lng=payload.domicile_lng,
    )
    db.add(new_user)

    # 3) Fetch the 'member' role
    member_role = db.query(models.Role).filter(models.Role.role_name == "member").first()
    if not member_role:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Default role 'member' is not configured.",
        )

    # 4) Attach role via relationship — populates user_roles
    new_user.roles.append(member_role)

    db.commit()
    db.refresh(new_user)

    return {
        "user_id": new_user.user_id,
        "username": new_user.username,
        "email": new_user.email,
        "roles": [r.role_name for r in new_user.roles],
    }


@router.get("/me")
def get_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    payload: dict = Depends(get_token_payload),  # <-- add this
):
    allowed = get_allowed_standard_ids(db, current_user.user_id)

    # Whether user has MFA configured/enabled (adjust field names to your schema)
    mfa_enabled = bool(
        getattr(current_user, "mfa_enabled", False)
        or getattr(current_user, "twofa_enabled", False)
        or getattr(current_user, "is_mfa_enabled", False)
    )

    # Whether the CURRENT token/session is MFA-verified
    mfa_verified = _payload_shows_mfa_verified(payload)

    return {
        "user_id": current_user.user_id,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "email": current_user.email,
        "roles": [r.role_name for r in current_user.roles],
        "city": current_user.city,
        "state": current_user.state_province,
        "country": current_user.country,
        "domicile_lat": current_user.domicile_lat,
        "domicile_lng": current_user.domicile_lng,
        "allowed_standard_ids": allowed,

        # NEW:
        "mfa_enabled": mfa_enabled,
        "mfa_verified": mfa_verified,
    }

@router.get("/mfa/status")
def get_mfa_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    mfa = get_user_mfa_methods(db, current_user)

    passkeys = (
        db.query(WebAuthnCredential)
        .filter(WebAuthnCredential.user_id == current_user.user_id)
        .all()
    )

    return {
        "totp_enabled": mfa["totp_enabled"],
        "passkey_enabled": mfa["passkey_enabled"],
        "passkeys": [
            {
                "credential_id": p.credential_id,
                "device_name": p.device_name,
                "created_at": p.created_at,
                "last_used_at": p.last_used_at,
            }
            for p in passkeys
        ],
    }

@router.post("/reauth/password")
def reauth_with_password(
    payload: ReauthPasswordIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    claims: dict = Depends(get_jwt_claims),
):
    user = db.query(User).filter(User.user_id == current_user.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password",
        )

    extra = {
        "reauth_verified": True,
        "reauth_at": int(datetime.now(timezone.utc).timestamp()),
    }

    if claims.get("mfa_verified") is True:
        extra["mfa_verified"] = True

    if claims.get("mfa_method"):
        extra["mfa_method"] = claims.get("mfa_method")

    token = create_access_token(
        user_id=user.user_id,
        mfa_verified=claims.get("mfa_verified") is True,
        expires_minutes=60,
        extra=extra,
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "reauth_verified": True,
    }