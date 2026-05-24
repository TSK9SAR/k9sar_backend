import os
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
import logging

from app.database import get_db
from app.schemas.password_reset_schema import ForgotIn, ResetVerifyIn, ResetAcceptIn
from app.services.mailer import send_email
from app.services.tokens import new_token, token_hash
from app.services.links import frontend_url
from app.models.password_reset import PasswordReset as PasswordResetToken
from app.models.user import User  # adjust import
from app.services.auth_reset import verify_reset_token_and_get_user
from app.services.security import hash_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

RESET_TTL_MIN = int(os.getenv("RESET_TOKEN_TTL_MINUTES", "60"))

logger = logging.getLogger(__name__)

def send_password_reset_email(to_email: str, subject: str, text: str, html: str):
    try:
        send_email(
            to_email=to_email,
            reply_to=None,
            subject=subject,
            text_body=text,
            html_body=html,
        )
    except Exception as e:
        print(f"[RESET MAIL] FAILED: {type(e).__name__}: {e}", flush=True)
        raise

@router.post("/forgot")
def forgot_password(payload: ForgotIn, background: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Always returns ok to avoid account enumeration.
    If email exists, emails a reset link.
    """
    email = (payload.email or "").strip().lower()

    user = (
        db.query(User)
        .filter(func.lower(func.trim(User.email)) == email)
        .first()
    )

    logger.warning(
        "*** PASSWORD RESET REQUESTED *** email=%s found=%s user_id=%s",
        email,
        bool(user),
        getattr(user, "user_id", None),
    )

    if user:
        token = new_token()
        th = token_hash(token)
        expires = datetime.now(timezone.utc) + timedelta(minutes=RESET_TTL_MIN)

        db.add(PasswordResetToken(user_id=user.user_id, token_hash=th, expires_at=expires))
        db.commit()

        link = frontend_url("/reset-password", token=token)
        subject = "K9SAR password reset"
        text = f"Use this link to reset your password:\n\n{link}\n\nThis link expires in {RESET_TTL_MIN} minutes."
        html = f"<p>Use this link to reset your password:</p><p><a href='{link}'>{link}</a></p><p>Expires in {RESET_TTL_MIN} minutes.</p>"

        background.add_task(
            send_password_reset_email,
            user.email,
            subject,
            text,
            html,
        )

    return {"ok": True}

@router.post("/reset/verify")
def reset_verify(payload: ResetVerifyIn, db: Session = Depends(get_db)):
    th = token_hash(payload.token)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    row = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == th)
        .order_by(PasswordResetToken.reset_id.desc())
        .first()
    )
    if not row:
        return {"ok": False}

    exp = row.expires_at
    if exp is None:
        return {"ok": False}
    if exp.tzinfo is not None:
        exp = exp.astimezone(timezone.utc).replace(tzinfo=None)

    if row.used_at is not None or exp < now:
        return {"ok": False}

    return {"ok": True}


from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

@router.post("/reset/accept")
def reset_accept(payload: ResetAcceptIn, db: Session = Depends(get_db)):
    tok = (payload.token or "").strip()
    user = verify_reset_token_and_get_user(db, tok)

    # update password


    user.password_hash = hash_password(payload.new_password)


    # optional username update (with uniqueness check)
    u = (payload.username or "").strip()
    if u:
        taken = (
            db.query(User.user_id)
            .filter(func.lower(User.username) == func.lower(u))
            .filter(User.user_id != user.user_id)
            .first()
        )
        if taken:
            raise HTTPException(status_code=409, detail="Username already taken")

        user.username = u

    # mark token used (latest row for this token)
    th = token_hash(tok)
    row = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == th)
        .order_by(PasswordResetToken.reset_id.desc())
        .first()
    )
    if row:
        row.used_at = datetime.now(timezone.utc).replace(tzinfo=None)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Username already taken")

    return {"ok": True}
