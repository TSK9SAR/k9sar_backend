import hashlib
import secrets
from datetime import datetime, timedelta

def new_invite_token() -> str:
    # URL-safe, high entropy
    return secrets.token_urlsafe(32)

def hash_token(token: str) -> str:
    # sha256 hex (64 chars)
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def default_expiry(hours: int = 72) -> datetime:
    return datetime.utcnow() + timedelta(hours=hours)
