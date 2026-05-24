from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.user import User

try:
    from app.models.user import AuthEvent
    
except Exception:
    AuthEvent = None  # optional table not yet installed


def utcnow() -> datetime:
    return datetime.utcnow()


def _client_ip(request: Optional[Request]) -> Optional[str]:
    if not request or not request.client:
        return None
    return request.client.host


def _user_agent(request: Optional[Request]) -> Optional[str]:
    if not request:
        return None
    return request.headers.get("user-agent")

def get_real_client_ip(request: Request) -> str | None:
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()

    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        # first IP is the original client
        return x_forwarded_for.split(",")[0].strip()

    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip:
        return x_real_ip.strip()

    if request.client:
        return request.client.host

    return None

def _log_event(
    db: Session,
    *,
    user_id: int,
    event_type: str,
    request: Optional[Request] = None,
    success: bool = True,
    detail: Optional[str] = None,
) -> None:
    if AuthEvent is None:
        return

    row = AuthEvent(
        user_id=user_id,
        event_type=event_type,
        ip_address=get_real_client_ip(request),
        user_agent=_user_agent(request),
        success=success,
        detail=detail,
    )
    db.add(row)


def mark_login_success(
    db: Session,
    *,
    user: User,
    request: Optional[Request] = None,
    commit: bool = True,
) -> None:
    now = utcnow()
    user.last_login_at = now
    user.last_seen_at = now
    user.login_count = int(user.login_count or 0) + 1
    db.add(user)

    _log_event(
        db,
        user_id=user.user_id,
        event_type="login",
        request=request,
        success=True,
    )

    if commit:
        db.commit()


def mark_mfa_success(
    db: Session,
    *,
    user: User,
    request: Optional[Request] = None,
    method: str | None = None,
    commit: bool = True,
) -> None:
    now = utcnow()
    user.last_mfa_verified_at = now
    user.last_seen_at = now
    user.mfa_verify_count = int(user.mfa_verify_count or 0) + 1
    db.add(user)

    # 🔥 log event here (centralized)
    detail = f"method={method}" if method else None

    _log_event(
        db,
        user_id=user.user_id,
        event_type="mfa_verify",
        request=request,
        success=True,
        detail=detail,
    )

    if commit:
        db.commit()


def touch_last_seen(
    db: Session,
    *,
    user: User,
    threshold_minutes: int = 3,
    commit: bool = True,
) -> None:
    now = utcnow()
    cutoff = now - timedelta(minutes=threshold_minutes)

    if not user.last_seen_at or user.last_seen_at < cutoff:
        user.last_seen_at = now
        db.add(user)
        if commit:
            db.commit()


def is_active_now(user: User, window_minutes: int = 15) -> bool:
    if not user.last_seen_at:
        return False
    return user.last_seen_at >= utcnow() - timedelta(minutes=window_minutes)