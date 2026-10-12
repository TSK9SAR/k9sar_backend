"""Read-only invitation history. Never return invitation tokens or token hashes."""
from datetime import datetime, timezone
from math import ceil
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.user_invite import UserInvite
from app.schemas.invite_schema import InviteHistoryOut
from app.utils.auth import require_admin

router = APIRouter(prefix="/admin/invites", tags=["invites"], dependencies=[Depends(require_admin)])


def _utcnow():
    return datetime.now(timezone.utc)


def _as_utc(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@router.get("", response_model=InviteHistoryOut)
def list_invitations(
    response: Response,
    status: Literal["all", "pending", "completed", "expired"] = "all",
    q: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    evaluated_at = _utcnow()
    now_naive = evaluated_at.replace(tzinfo=None)
    # Acceptance wins even when the invitation's original expiry date is past.
    # '<' matches the existing verify/accept endpoints at the expiry boundary.
    status_value = case(
        (UserInvite.used_at.is_not(None), "completed"),
        (UserInvite.expires_at < now_naive, "expired"),
        else_="pending",
    )
    filters = []
    search = q.strip()
    if search:
        full_name = func.coalesce(UserInvite.first_name, "") + " " + func.coalesce(UserInvite.last_name, "")
        filters.append(or_(UserInvite.email.icontains(search, autoescape=True),
                           full_name.icontains(search, autoescape=True)))

    counts_row = db.query(
        func.count(UserInvite.invite_id),
        func.sum(case((status_value == "pending", 1), else_=0)),
        func.sum(case((status_value == "completed", 1), else_=0)),
        func.sum(case((status_value == "expired", 1), else_=0)),
    ).filter(*filters).one()
    counts = dict(zip(("all", "pending", "completed", "expired"), (int(count or 0) for count in counts_row)))
    if status != "all":
        filters.append(status_value == status)

    # Select only fields required for display; no secrets, password fields, or phone numbers.
    rows = db.query(
        UserInvite.invite_id, UserInvite.email, UserInvite.first_name, UserInvite.last_name,
        UserInvite.created_at, UserInvite.expires_at, UserInvite.used_at,
        User.first_name.label("issuer_first_name"), User.last_name.label("issuer_last_name"),
        User.email.label("issuer_email"), status_value.label("invitation_status"),
    ).outerjoin(User, User.user_id == UserInvite.created_by_user_id).filter(*filters).order_by(
        UserInvite.created_at.desc(), UserInvite.invite_id.desc(),
    ).offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for row in rows:
        issuer_name = " ".join(part.strip() for part in (row.issuer_first_name, row.issuer_last_name) if part and part.strip())
        expires_at = _as_utc(row.expires_at)
        items.append({
            "invite_id": row.invite_id,
            "email": row.email,
            "first_name": row.first_name,
            "last_name": row.last_name,
            "created_by_name": issuer_name or row.issuer_email,
            "created_at": _as_utc(row.created_at),
            "expires_at": expires_at,
            "completed_at": _as_utc(row.used_at),
            "status": row.invitation_status,
            "remaining_seconds": max(0, ceil((expires_at - evaluated_at).total_seconds())) if row.invitation_status == "pending" else 0,
        })
    return {"items": items, "total": counts[status], "counts": counts,
            "page": page, "page_size": page_size, "evaluated_at": evaluated_at}
