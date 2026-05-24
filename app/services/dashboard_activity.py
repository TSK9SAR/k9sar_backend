# app/services/dashboard_activity.py
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

# import your models
from app.models import Certification, Team, User, Dog, Standard  # adjust names

def _full_name(u: User) -> str:
    first = (getattr(u, "first_name", "") or "").strip()
    last = (getattr(u, "last_name", "") or "").strip()
    name = (f"{first} {last}").strip()
    return name or (getattr(u, "username", "") or "").strip() or "Unknown"

def get_recent_cert_activity(db: Session, window_days: int = 90, limit: int = 50) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=window_days)

    # Aliases for the two user joins: handler + actor
    from sqlalchemy.orm import aliased
    HandlerUser = aliased(User)
    ActorUser = aliased(User)

    # Base query joins needed to resolve handler/dog/discipline/actor
    base = (
        db.query(
            Certification.certification_id,
            Certification.team_id,
            Certification.created_at,
            Certification.updated_at,
            Certification.status,
            Certification.supervisor_id,

            Team.team_id,

            Dog.dog_id,
            Dog.dog_name,

            HandlerUser.user_id.label("handler_user_id"),
            HandlerUser.first_name.label("handler_first"),
            HandlerUser.last_name.label("handler_last"),
            HandlerUser.username.label("handler_username"),

            ActorUser.user_id.label("actor_user_id"),
            ActorUser.first_name.label("actor_first"),
            ActorUser.last_name.label("actor_last"),
            ActorUser.username.label("actor_username"),

            Standard.standard_id,
            Standard.discipline.label("discipline"),
        )
        .join(Team, Certification.team_id == Team.team_id)
        .join(Dog, Team.dog_id == Dog.dog_id)  # adjust if your Team has a different dog FK
        .join(HandlerUser, Team.handler_user_id == HandlerUser.user_id)  # adjust if Team uses member_id
        .outerjoin(ActorUser, Certification.supervisor_id == ActorUser.user_id)
        .join(Standard, Certification.standard_id == Standard.standard_id)
    )

    # Issued events
    issued_rows = (
        base.filter(Certification.created_at >= window_start)
        .all()
    )

    # Revoked events (status revoked, updated recently)
    revoked_rows = (
        base.filter(
            and_(
                Certification.updated_at >= window_start,
                Certification.status == "revoked",
            )
        )
        .all()
    )

    events: List[Dict[str, Any]] = []

    def handler_name_from_row(r) -> str:
        first = (r.handler_first or "").strip()
        last = (r.handler_last or "").strip()
        nm = (f"{first} {last}").strip()
        return nm or (r.handler_username or "").strip() or "Unknown"

    def actor_name_from_row(r) -> str:
        first = (r.actor_first or "").strip()
        last = (r.actor_last or "").strip()
        nm = (f"{first} {last}").strip()
        return nm or (r.actor_username or "").strip() or "Unknown"

    for r in issued_rows:
        events.append({
            "when": r.created_at,
            "action": "issued",
            "actor_user_id": r.actor_user_id,
            "actor_name": actor_name_from_row(r),
            "team_id": r.team_id,
            "handler_name": handler_name_from_row(r),
            "dog_name": r.dog_name,
            "discipline": r.discipline,
        })

    for r in revoked_rows:
        events.append({
            "when": r.updated_at,
            "action": "revoked",
            "actor_user_id": r.actor_user_id,
            "actor_name": actor_name_from_row(r),
            "team_id": r.team_id,
            "handler_name": handler_name_from_row(r),
            "dog_name": r.dog_name,
            "discipline": r.discipline,
        })

    # Sort newest first and limit
    events.sort(key=lambda e: e["when"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return events[:limit]
