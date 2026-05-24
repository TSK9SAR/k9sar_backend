# app/utils/hashing.py
from passlib.context import CryptContext
import json

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password):
    """Deep debug: detect type, size, and content sample of what's being hashed."""
    try:
        # print(f"[DEBUG] Incoming password type: {type(password)}")
        # if isinstance(password, (dict, list)):
        #     # print(f"[DEBUG] JSON-like object passed: {json.dumps(password)[:200]}...")
        # elif isinstance(password, bytes):
        #     # print(f"[DEBUG] Raw bytes length: {len(password)}")
        # elif isinstance(password, str):
        #     # print(f"[DEBUG] String length: {len(password)} - preview: {password[:20]}")
        # else:
        #     # print(f"[DEBUG] Unknown password type: {password}")

        # Normalize safely
        if isinstance(password, bytes):
            password = password.decode("utf-8", errors="ignore")
        elif not isinstance(password, str):
            password = str(password)

        # Truncate after encoding
        encoded = password.encode("utf-8")[:72]
        result = pwd_context.hash(encoded.decode("utf-8", errors="ignore"))
        # print("[DEBUG] Successfully hashed password.")
        return result
    except Exception as e:
        # print(f"[ERROR] Hashing failure: {e}")
        raise

def verify_password(plain_password, hashed_password):
    if isinstance(plain_password, bytes):
        plain_password = plain_password.decode("utf-8", errors="ignore")
    encoded = plain_password.encode("utf-8")[:72]
    return pwd_context.verify(encoded.decode("utf-8", errors="ignore"), hashed_password)
