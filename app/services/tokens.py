import secrets
import hashlib

def new_token() -> str:
    return secrets.token_urlsafe(32)

def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
