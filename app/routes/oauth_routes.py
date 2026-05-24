from datetime import datetime, timedelta
from typing import Optional, Any
from sqlalchemy import or_
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session, joinedload
from app.settings import JWT_SECRET, JWT_ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from app.database import get_db
from app.utils.jwt_handler import create_access_token
from app.models.user import User  # adjust if your User model file is elsewhere
from app.utils.auth import requires_2fa
from app.utils.auth import oauth2_scheme

# =====================================================
# CONFIG
# =====================================================


router = APIRouter(prefix="/auth", tags=["Authentication"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# =====================================================
# HELPERS
# =====================================================


def get_user_by_username(db: Session, username: str):
    return (
        db.query(User)
        .options(joinedload(User.roles))
        .filter(User.username == username)
        .first()
    )

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)



# =====================================================
# ENDPOINTS
# =====================================================
@router.post("/token")
def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = get_user_by_username(db, form_data.username)
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        user.user_id,
        mfa_verified=False,
        expires_minutes=120,
        extra={"typ": "access"},
    )
    return {"access_token": access_token, "token_type": "bearer"}

# -----------------------------------------------------
# Example protected route
# -----------------------------------------------------
@router.get("/me")
def read_users_me(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])

        sub = payload.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail="Invalid token")

        try:
            user_id = int(sub)
        except (TypeError, ValueError):
            raise HTTPException(status_code=401, detail="Invalid token")

        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")

        return {
            "user_id": user.user_id,
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }

    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


