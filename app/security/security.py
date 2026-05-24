# # app/core/security.py (or similar)
# from datetime import datetime, timedelta
# from typing import Any, Optional

# from jose import jwt

# SECRET_KEY = "your-long-secret"  # same everywhere
# ALGORITHM = "HS256"
# ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24


# def create_access_token(
#     subject: str | int, expires_delta: Optional[timedelta] = None
# ) -> str:
#     if expires_delta is None:
#         expires_delta = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

#     to_encode: dict[str, Any] = {
#         "sub": str(subject),  # 👈 IMPORTANT: canonical claim
#         "exp": datetime.utcnow() + expires_delta,
#     }
#     encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
#     return encoded_jwt
