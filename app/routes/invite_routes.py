import os
import json
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.database import get_db
from app.models.user_invite import UserInvite
from app.schemas.invite_schema import InviteCreateIn, InviteAcceptIn
from app.services.links import frontend_url
from app.services.mailer import send_email
from app.services.tokens import new_token, token_hash
from app.utils.auth import get_current_user, require_supervisor

from app.models.role import Role
from app.models.user import User
from app.utils.passwords import hash_password

router = APIRouter(tags=["invites"])

INVITE_TTL_DAYS = int(os.getenv("INVITE_TOKEN_TTL_DAYS", "14"))


def utcnow_naive() -> datetime:
    """UTC time but tz-naive (best with MySQL DATETIME)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_naive_utc(dt: datetime) -> datetime:
    """Ensure datetime is UTC-naive for safe comparisons with MySQL DATETIME."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


@router.post("/admin/invites")
def create_invite(
    payload: InviteCreateIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(require_supervisor),
):

    token = new_token()
    th = token_hash(token)
    expires = utcnow_naive() + timedelta(days=INVITE_TTL_DAYS)

    invite = UserInvite(
        user_id=None,  # account-level invite; user may not exist yet
        email=payload.email,
        first_name=payload.first_name,
        last_name=payload.last_name,
        phone=payload.phone,
        token_hash=th,
        expires_at=expires,
        created_by_user_id=getattr(current_user, "user_id", None),
    )

    # Store roles from payload into role_ids_json (via helper on model)
    try:
        invite.set_role_ids(payload.role_ids)
    except Exception:
        # If set_role_ids isn't present yet, you can remove this and store directly
        # invite.role_ids_json = json.dumps(payload.role_ids)
        pass

    db.add(invite)
    db.commit()

    # Frontend is mounted at /app (BrowserRouter basename="/app")
    link = frontend_url("/accept-invite", token=token)

    email_sent = False

    try:
        send_email(
            to_email=invite.email,
            reply_to=None,
            subject="K9SAR Invitation",
            text_body=(
                f"Hi {invite.first_name or ''},\n\n"
                "You have been invited to join TSK9SAR. Please click the link below to accept the invitation:\n\n"
                f"{link}\n\n"
                "If you did not expect this invitation, please ignore this email.\n\n"
                "Best regards,\n"
                "TSK9SAR Team"
            ),
            html_body=(
                f"<p>Hi {invite.first_name or ''},</p>"
                "<p>You have been invited to join TSK9SAR.</p>"
                f"<p><a href='{link}'>Accept invitation</a></p>"
                "<p>If you did not expect this invitation, please ignore this email.</p>"
                "<p>Best regards,<br>TSK9SAR Team</p>"
            ),
        )
        email_sent = True
        
    except Exception as e:
        print(f"[INVITE MAIL] failed for invite_id={invite.invite_id}: {e}")
        email_sent = False

    return {
        "ok": True,
        "invite_url": link,
        "expires_at": expires.isoformat(),
        "email_sent": email_sent,
    }



@router.post("/auth/invite/verify")
def verify_invite(payload: dict, db: Session = Depends(get_db)):
    token = (payload.get("token") or "").strip()
    token = token.replace(" ", "+")  # harmless for token_urlsafe; helps if '+' got turned into space
    th = token_hash(token)
    now = utcnow_naive()

    row = (
        db.query(UserInvite)
        .filter(UserInvite.token_hash == th)
        .first()
    )
    if not row:
        return {"valid": False}

    exp = normalize_naive_utc(row.expires_at)
    used = row.used_at  # if your DB uses accepted_at instead, rename this line + checks below

    if used is not None or exp < now:
        return {"valid": False}

    # Return only account-level info (no team_id)
    # If you want role_ids back, you can add row.get_role_ids() here.
    return {
        "valid": True,
        "email": row.email,
        "first_name": getattr(row, "first_name", None),
        "last_name": getattr(row, "last_name", None),
        "phone": getattr(row, "phone", None),
    }


@router.post("/auth/invite/accept")
def accept_invite(payload: InviteAcceptIn, db: Session = Depends(get_db)):
    token = (payload.token or "").strip().replace(" ", "+")
    th = token_hash(token)
    now = utcnow_naive()

    invite = db.query(UserInvite).filter(UserInvite.token_hash == th).first()
    if not invite:
        return {"ok": False, "reason": "invalid"}

    exp = normalize_naive_utc(invite.expires_at)
    if invite.used_at is not None or exp < now:
        return {"ok": False, "reason": "expired_or_used"}

    username = (payload.username or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="username required")

    # 1) Create or load user (by email)
    user = db.query(User).filter(User.email == invite.email).first()
    if not user:
        user = User(
            email=invite.email,
            username=username,
            first_name=getattr(invite, "first_name", None),
            last_name=getattr(invite, "last_name", None),
            phone=getattr(invite, "phone", None),
        )

        # IMPORTANT: adjust this field name to match your User model
        user.password_hash = hash_password(payload.password)

        db.add(user)
        try:
            db.flush()  # assigns user.user_id
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="Username or email already exists")
    else:
        # user exists: set/replace password, optionally username if missing
        user.password_hash = hash_password(payload.password)
        if not getattr(user, "username", None):
            user.username = username

    # 2) Assign roles via relationship (uses user_roles association table)
    role_ids = []
    if hasattr(invite, "get_role_ids"):
        role_ids = invite.get_role_ids()
    else:
        # fallback if you didn't implement helper yet
        try:
            role_ids = json.loads(getattr(invite, "role_ids_json", "[]") or "[]")
        except Exception:
            role_ids = []

    if role_ids:
        roles = db.query(Role).filter(Role.role_id.in_(role_ids)).all()
        # avoid duplicates
        existing_ids = {r.role_id for r in (user.roles or [])}
        for r in roles:
            if r.role_id not in existing_ids:
                user.roles.append(r)

    # 3) Mark invite used and link to user
    invite.user_id = user.user_id
    invite.used_at = now

    db.commit()
    return {"ok": True, "user_id": user.user_id}
