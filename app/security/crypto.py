# app/security/crypto.py

from cryptography.fernet import Fernet
import os

def _fernet() -> Fernet:
    key = os.environ.get("FERNET_KEY")
    if not key:
        raise RuntimeError("FERNET_KEY not set")
    return Fernet(key.encode())

def encrypt_str(s: str) -> bytes:
    return _fernet().encrypt(s.encode())

def decrypt_bytes(b: bytes) -> str:
    return _fernet().decrypt(b).decode()
