from datetime import datetime, timedelta, timezone
import json
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from webauthn import (
    generate_registration_options,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
    options_to_json,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
    PublicKeyCredentialDescriptor,
    PublicKeyCredentialType,
)

from app.database import get_db
from app.models.user import User
from app.models.webauthn_credential import WebAuthnCredential
from app.utils.auth import get_current_user, require_recent_reauth
from app.utils.jwt_handler import create_access_token, decode_access_token
from fastapi import Request
from app.services.auth_activity import mark_mfa_success

WEBAUTHN_RP_ID = os.getenv("WEBAUTHN_RP_ID")
WEBAUTHN_RP_NAME = os.getenv("WEBAUTHN_RP_NAME")
WEBAUTHN_ORIGIN = os.getenv("WEBAUTHN_ORIGIN")

router = APIRouter(prefix="/auth/passkey", tags=["passkey"])


# -------------------------------------------------------------------
# simple in-memory challenge store for first implementation only
# key: (purpose, user_id) -> {"challenge": str|bytes, "expires_at": datetime}
# -------------------------------------------------------------------

_WEBAUTHN_CHALLENGES: dict[tuple[str, int], dict] = {}
CHALLENGE_TTL_SECONDS = 300


def save_webauthn_challenge_for_user(*, user_id: int, purpose: str, challenge) -> None:
    _WEBAUTHN_CHALLENGES[(purpose, user_id)] = {
        "challenge": challenge,
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=CHALLENGE_TTL_SECONDS),
    }


def load_webauthn_challenge_for_user(*, user_id: int, purpose: str):
    item = _WEBAUTHN_CHALLENGES.get((purpose, user_id))
    if not item:
        return None

    if item["expires_at"] < datetime.now(timezone.utc):
        _WEBAUTHN_CHALLENGES.pop((purpose, user_id), None)
        return None

    return item["challenge"]


def delete_webauthn_challenge_for_user(user_id: int, purpose: str) -> None:
    _WEBAUTHN_CHALLENGES.pop((purpose, user_id), None)


def get_user_id_from_twofa_token(twofa_token: str) -> int:
    payload = decode_access_token(twofa_token)
    if not payload:
        raise HTTPException(status_code=400, detail="Invalid 2FA token")

    if payload.get("typ") != "2fa":
        raise HTTPException(status_code=400, detail="Invalid 2FA token type")

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=400, detail="2FA token missing subject")

    return int(sub)


# -------------------------------------------------------------------
# request schemas
# -------------------------------------------------------------------

class PasskeyRegisterFinishIn(BaseModel):
    credential: dict
    device_name: str | None = None


class PasskeyAuthStartIn(BaseModel):
    twofa_token: str


class PasskeyAuthFinishIn(BaseModel):
    twofa_token: str
    credential: dict


# -------------------------------------------------------------------
# registration
# -------------------------------------------------------------------

@router.post("/register/start")
def passkey_register_start(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing = (
        db.query(WebAuthnCredential)
        .filter(WebAuthnCredential.user_id == current_user.user_id)
        .all()
    )

    exclude_credentials = [
        PublicKeyCredentialDescriptor(
            id=base64url_to_bytes(cred.credential_id),
            type=PublicKeyCredentialType.PUBLIC_KEY,
        )
        for cred in existing
        if cred.credential_id
    ]

    options = generate_registration_options(
        rp_id=WEBAUTHN_RP_ID,
        rp_name=WEBAUTHN_RP_NAME,
        user_id=str(current_user.user_id).encode("utf-8"),
        user_name=current_user.email,
        user_display_name=(
            f"{current_user.first_name} {current_user.last_name}".strip()
            or current_user.email
        ),
        exclude_credentials=exclude_credentials,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )

    save_webauthn_challenge_for_user(
        user_id=current_user.user_id,
        purpose="register",
        challenge=options.challenge,
    )

    return json.loads(options_to_json(options))

@router.post("/register/finish")
def passkey_register_finish(
    request: Request,
    payload: PasskeyRegisterFinishIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    expected_challenge = load_webauthn_challenge_for_user(
        user_id=current_user.user_id,
        purpose="register",
    )
    if not expected_challenge:
        raise HTTPException(status_code=400, detail="Registration challenge missing or expired")

    verification = verify_registration_response(
        credential=payload.credential,
        expected_challenge=expected_challenge,
        expected_rp_id=WEBAUTHN_RP_ID,
        expected_origin=WEBAUTHN_ORIGIN,
        require_user_verification=False,
    )

    credential_id = payload.credential.get("rawId")
    if not credential_id:
        raise HTTPException(status_code=400, detail="Registration missing rawId")

    pk_bytes = verification.credential_public_key
    if not pk_bytes:
        raise HTTPException(status_code=500, detail="Registration produced empty public key")

    pk_b64 = bytes_to_base64url(pk_bytes)
    if not pk_b64:
        raise HTTPException(status_code=500, detail="Registration produced invalid public key")

    transports = (
        ",".join(payload.credential.get("response", {}).get("transports", []))
        if payload.credential.get("response")
        else None
    )

    existing = (
        db.query(WebAuthnCredential)
        .filter(WebAuthnCredential.credential_id == credential_id)
        .first()
    )

    if existing:
        existing.user_id = current_user.user_id
        existing.public_key = pk_b64
        existing.sign_count = verification.sign_count
        existing.transports = transports
        existing.device_name = payload.device_name
        existing.backed_up = getattr(verification, "credential_backed_up", None)
        existing.last_used_at = None
        db.add(existing)
    else:
        cred = WebAuthnCredential(
            credential_id=credential_id,
            user_id=current_user.user_id,
            public_key=pk_b64,
            sign_count=verification.sign_count,
            transports=transports,
            device_name=payload.device_name,
            backed_up=getattr(verification, "credential_backed_up", None),
        )
        db.add(cred)

    mark_mfa_success(db, user=current_user, request=request, method="passkey", commit=False)

    db.commit()
    db.refresh(current_user)

    delete_webauthn_challenge_for_user(current_user.user_id, "register")

    access_token = create_access_token(
        current_user.user_id,
        mfa_verified=True,
        extra={"mfa_method": "passkey"},
    )

    return {
        "ok": True,
        "access_token": access_token,
        "token_type": "bearer",
    }


# -------------------------------------------------------------------
# authentication for MFA
# -------------------------------------------------------------------

@router.post("/authenticate/start")
def passkey_authenticate_start(
    payload: PasskeyAuthStartIn,
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_twofa_token(payload.twofa_token)

    creds = (
        db.query(WebAuthnCredential)
        .filter(WebAuthnCredential.user_id == user_id)
        .all()
    )
    if not creds:
        raise HTTPException(status_code=404, detail="No passkeys enrolled")

    allow_credentials = [
        PublicKeyCredentialDescriptor(
            id=base64url_to_bytes(cred.credential_id),
            type=PublicKeyCredentialType.PUBLIC_KEY,
        )
        for cred in creds
        if cred.credential_id
    ]

    options = generate_authentication_options(
        rp_id=WEBAUTHN_RP_ID,
        allow_credentials=allow_credentials,
        user_verification=UserVerificationRequirement.PREFERRED,
    )

    save_webauthn_challenge_for_user(
        user_id=user_id,
        purpose="authenticate",
        challenge=options.challenge,
    )

    return json.loads(options_to_json(options))


@router.post("/authenticate/finish")
def passkey_authenticate_finish(
    request: Request,
    payload: PasskeyAuthFinishIn,
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_twofa_token(payload.twofa_token)

    expected_challenge = load_webauthn_challenge_for_user(
        user_id=user_id,
        purpose="authenticate",
    )
    if not expected_challenge:
        raise HTTPException(status_code=400, detail="Authentication challenge missing or expired")

    credential_id = payload.credential.get("rawId") or payload.credential.get("id")

    if not credential_id:
        raise HTTPException(status_code=400, detail="Missing credential id")

    stored = (
        db.query(WebAuthnCredential)
        .filter(WebAuthnCredential.credential_id == credential_id)
        .first()
    )

    if not stored:
        raise HTTPException(status_code=400, detail="Unknown credential")

    if stored.user_id != user_id:
        raise HTTPException(status_code=400, detail="Credential user mismatch")

    if not stored.public_key:
        raise HTTPException(status_code=400, detail="Stored credential has no public key")

    decoded_pk = base64url_to_bytes(stored.public_key)

    if not decoded_pk:
        raise HTTPException(status_code=400, detail="Stored credential public key is invalid")

    verification = verify_authentication_response(
        credential=payload.credential,
        expected_challenge=expected_challenge,
        expected_rp_id=WEBAUTHN_RP_ID,
        expected_origin=WEBAUTHN_ORIGIN,
        credential_public_key=decoded_pk,
        credential_current_sign_count=stored.sign_count,
        require_user_verification=False,
    )

    stored.sign_count = verification.new_sign_count
    stored.last_used_at = datetime.now(timezone.utc)

    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid user")

    mark_mfa_success(db, user=user, request=request, method="passkey", commit=False)

    db.add(stored)
    db.commit()
    db.refresh(stored)
    db.refresh(user)

    delete_webauthn_challenge_for_user(user_id, "authenticate")

    access_token = create_access_token(
        user_id,
        mfa_verified=True,
        extra={"mfa_method": "passkey"},
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
    }

@router.post("/disable")
def passkey_disable(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    _ = Depends(require_recent_reauth),
):
    user_id = getattr(current_user, "user_id", None) or getattr(current_user, "id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    deleted = (
        db.query(WebAuthnCredential)
        .filter(WebAuthnCredential.user_id == int(user_id))
        .delete(synchronize_session=False)
    )
    db.commit()

    token = create_access_token(
        user_id=current_user.user_id,
        mfa_verified=False,
        extra={"reauth_verified": False},
    )

    return {
        "ok": True,
        "access_token": token,
        "token_type": "bearer",
    }

