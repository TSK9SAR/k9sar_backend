import base64
from io import BytesIO

import pyotp
import qrcode
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security.crypto import encrypt_str, decrypt_bytes
from app.utils.auth import get_current_user, require_recent_reauth, requires_2fa
from app.utils.jwt_handler import verify_access_token, create_access_token

from fastapi import Request
from app.services.auth_activity import mark_mfa_success


router = APIRouter(prefix="/auth/2fa", tags=["auth-2fa"])


# ----------------------------
# Schemas
# ----------------------------

class TwoFABeginOut(BaseModel):
    # Keep both "new" and "old" names so frontend/backends don’t drift again
    otpauth_uri: str

    # New style
    secret_base32: str
    qr_png_data_url: str  # data:image/png;base64,...

    # Old style (compat)
    secret: str
    qr_png_base64: str  # base64 only (no data: prefix)


class TwoFAConfirmIn(BaseModel):
    code: str


class TwoFAVerifyIn(BaseModel):
    twofa_token: str
    code: str


# ----------------------------
# Helpers
# ----------------------------

def _decrypt_user_twofa_secret(user: User) -> str:
    """
    twofa_secret is stored as TEXT in DB:
      base64( encrypt_str(secret_base32) )
    Return plaintext base32 secret.
    """
    secret_enc_text = getattr(user, "twofa_secret", None)
    if not secret_enc_text:
        raise HTTPException(status_code=400, detail="2FA secret missing")

    if not isinstance(secret_enc_text, str):
        # In case legacy data ends up as bytes or something odd
        try:
            secret_enc_text = secret_enc_text.decode("utf-8")
        except Exception:
            secret_enc_text = str(secret_enc_text)

    try:
        enc_bytes = base64.b64decode(secret_enc_text)
        secret = decrypt_bytes(enc_bytes)
        secret = "".join(secret.split()).upper()
        return secret
    except Exception:
        raise HTTPException(status_code=500, detail="2FA secret could not be decrypted")


def _normalize_code(code: str) -> str:
    c = (code or "").strip().replace(" ", "")
    if not (len(c) == 6 and c.isdigit()):
        raise HTTPException(status_code=422, detail="Code must be 6 digits")
    return c


# ----------------------------
# Routes
# ----------------------------

@router.post("/begin", response_model=TwoFABeginOut)
def begin_2fa(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Only evaluators/admins (per your requires_2fa definition) may set up 2FA
    if not requires_2fa(db, current_user):
        raise HTTPException(status_code=403, detail="2FA setup is only available for evaluators.")

    # Generate new secret and otpauth URI
    secret = pyotp.random_base32()
    otpauth_uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=current_user.email,
        issuer_name="K9SAR",
    )

    # Store encrypted secret as base64 text (because DB column is str)
    enc_bytes = encrypt_str(secret)  # bytes
    current_user.twofa_secret = base64.b64encode(enc_bytes).decode("ascii")
    current_user.twofa_enabled = True
    current_user.twofa_confirmed = False
    db.add(current_user)
    db.commit()

    # QR image
    img = qrcode.make(otpauth_uri)
    buf = BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    return {
        "otpauth_uri": otpauth_uri,

        # new
        "secret_base32": secret,
        "qr_png_data_url": f"data:image/png;base64,{qr_b64}",

        # old compat
        "secret": secret,
        "qr_png_base64": qr_b64,
    }


@router.post("/confirm")
def confirm_twofa_setup(
    payload: TwoFAConfirmIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Confirm is for finishing setup (current_user), NOT the step-up token flow
    if not getattr(current_user, "twofa_enabled", False):
        raise HTTPException(status_code=400, detail="2FA setup has not been started")

    # Decrypt stored secret -> base32
    secret = _decrypt_user_twofa_secret(current_user)

    code = _normalize_code(payload.code)

    totp = pyotp.TOTP(secret)
    if not totp.verify(code, valid_window=1):
        raise HTTPException(status_code=401, detail="Invalid 2FA code")

    current_user.twofa_confirmed = True
    db.add(current_user)
    db.commit()

    # Optional: return upgraded access token immediately (mfa_verified=True)
    access_token = create_access_token(
        current_user.user_id,
        mfa_verified=True,
        expires_minutes=120,   # <-- choose your session length
        extra={"typ": "access"},
    )
    return {"ok": True, "twofa_enabled": True, "twofa_confirmed": True, "access_token": access_token, "token_type": "bearer"}



@router.post("/verify")
def verify_twofa(
    request: Request,
    payload: TwoFAVerifyIn,
    db: Session = Depends(get_db),
):
    # Step-up verification for login: uses a short-lived twofa_token
    try:
        tok = (payload.twofa_token or "").strip()
        decoded = verify_access_token(tok)
        if not decoded or decoded.get("typ") != "2fa":
            raise HTTPException(status_code=401, detail="Invalid 2FA token")

        user_id = int(decoded.get("sub"))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid 2FA token")

    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid 2FA token")

    if not getattr(user, "twofa_enabled", False) or not getattr(user, "twofa_confirmed", False):
        raise HTTPException(status_code=400, detail="2FA is not enabled for this user")

    secret = _decrypt_user_twofa_secret(user)

    code = _normalize_code(payload.code)

    totp = pyotp.TOTP(secret)
    if not totp.verify(code, valid_window=1):
        raise HTTPException(status_code=401, detail="Invalid 2FA code")


    mark_mfa_success(db, user=user, request=request, method="totp", commit=False)

    db.commit()
    db.refresh(user)

    access_token = create_access_token(
        user_id,
        mfa_verified=True,
        extra={"mfa_method": "totp"},
    )
    return {
        "ok": True,
        "access_token": access_token,
        "token_type": "bearer",
    }

@router.post("/totp/disable")
def disable_totp(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _ = Depends(require_recent_reauth),
):
    user = db.query(User).filter(User.user_id == current_user.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # --current_user.twofa_enabled = False
    current_user.twofa_confirmed = False
    current_user.twofa_secret = None
    db.add(current_user)
    user.totp_secret = None
    user.twofa_enabled = False  # adjust to your logic
    db.commit()

    # --- STEP 2: ISSUE CLEAN TOKEN (THIS IS #6) ---
    token = create_access_token(
        user_id=user.user_id,
        mfa_verified=False,        # no longer MFA verified
        expires_minutes=60,
        extra={
            "reauth_verified": False,   # clear reauth flag
        },
    )

    # --- STEP 3: return it ---
    return {
        "ok": True,
        "access_token": token,
        "token_type": "bearer",
    }