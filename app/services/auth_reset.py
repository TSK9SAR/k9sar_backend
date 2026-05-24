from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.services.tokens import token_hash
from app.models.password_reset import PasswordReset as PasswordResetToken
from app.models.user import User


def verify_reset_token_and_get_user(db: Session, token: str) -> User:
    tok = (token or "").strip()
    if not tok:
        raise HTTPException(status_code=400, detail="Missing reset token")

    th = token_hash(tok)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    row = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == th)
        .order_by(PasswordResetToken.reset_id.desc())
        .first()
    )
    if not row:
        raise HTTPException(status_code=400, detail="Invalid reset token")

    # expires_at safety (naive compare)
    exp = row.expires_at
    if exp is None:
        raise HTTPException(status_code=400, detail="Invalid reset token")
    if exp.tzinfo is not None:
        exp = exp.astimezone(timezone.utc).replace(tzinfo=None)

    if row.used_at is not None:
        raise HTTPException(status_code=400, detail="Reset token already used")

    if exp < now:
        raise HTTPException(status_code=400, detail="Reset token expired")

    user = db.query(User).filter(User.user_id == row.user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="User not found")

    return user
