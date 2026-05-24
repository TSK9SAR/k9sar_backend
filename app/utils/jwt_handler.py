from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from jose import jwt, JWTError
from jose.exceptions import ExpiredSignatureError
import bcrypt
import os

ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")

def _jwt_secret() -> str:
    # support all names you may have used
    secret = os.environ.get("JWT_SECRET_KEY") or os.environ.get("JWT_SECRET") or os.environ.get("SECRET_KEY")
    if not secret:
        raise RuntimeError("JWT secret not configured (JWT_SECRET_KEY or JWT_SECRET or SECRET_KEY)")
    return secret


# --- Canonical low-level helpers (one secret source) ---

def encode_token(payload: Dict[str, Any]) -> str:
    return jwt.encode(payload, _jwt_secret(), algorithm=ALGORITHM)

def decode_access_token(token: str) -> dict:
    return jwt.decode(token, _jwt_secret(), algorithms=[ALGORITHM])

def verify_access_token(token: str):
    try:
        return decode_access_token(token)
    except ExpiredSignatureError:
        # print("JWT decode failed: expired")
        return None
    except JWTError as e:
        # print("JWT decode failed:", str(e))
        return None


# --- Your “new-style” creator (used by MFA gating) ---

# def create_access_token(
#     user_id: int,
#     *,
#     mfa_verified: bool = False,
#     expires_minutes: int = 60 * 24,
#     extra: Optional[Dict[str, Any]] = None,
# ) -> str:
#     now = datetime.now(timezone.utc)
#     payload: Dict[str, Any] = {
#         "sub": str(user_id),
#         "iat": int(now.timestamp()),
#         "exp": int((now + timedelta(minutes=expires_minutes)).timestamp()),
#         "mfa_verified": bool(mfa_verified),
#         "typ": "access",
#     }
#     if extra:
#         payload.update(extra)
#     return encode_token(payload)

def create_access_token(
    user_id: int,
    mfa_verified: bool = False,
    expires_minutes: int = 60,
    extra: dict | None = None,
) -> str:
    now = datetime.now(timezone.utc)

    payload = {
        "sub": str(user_id),
        "typ": "access",
        "mfa_verified": bool(mfa_verified),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=expires_minutes)).timestamp()),
    }

    if extra:
        payload.update(extra)

    return encode_token(payload)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False

# --- Compatibility wrapper for your existing routes that call:
# create_access_token(subject=..., expires_delta=..., extra=...)
def create_access_token_compat(
    *,
    subject: Any,
    expires_delta: Optional[timedelta] = None,
    extra: Optional[Dict[str, Any]] = None,
    mfa_verified: bool = False,
) -> str:
    minutes = int(expires_delta.total_seconds() // 60) if expires_delta else (60 * 24)
    return create_access_token(int(subject), mfa_verified=mfa_verified, expires_minutes=minutes, extra=extra)


