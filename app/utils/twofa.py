import base64
import pyotp
from app.security.crypto import decrypt_bytes


def verify_user_2fa_code(user, code: str) -> bool:
    """
    Return True if TOTP code is valid for this user.
    Returns False for any failure.
    Does NOT raise HTTPException.
    """

    if not getattr(user, "twofa_enabled", False):
        return False

    secret_enc = getattr(user, "twofa_secret", None)
    if not secret_enc:
        return False

    try:
        # stored as base64(encrypted_bytes)
        enc_bytes = base64.b64decode(secret_enc)
        secret = decrypt_bytes(enc_bytes)
        secret = "".join(secret.split()).upper()
    except Exception:
        return False

    c = (code or "").strip().replace(" ", "")
    if not (len(c) == 6 and c.isdigit()):
        return False

    try:
        totp = pyotp.TOTP(secret)
        return totp.verify(c, valid_window=1)
    except Exception:
        return False
