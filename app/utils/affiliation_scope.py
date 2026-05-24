from typing import Optional, Set

from fastapi import HTTPException, status
from sqlalchemy.orm import Query, Session

from app.models.user import User
from app.models.handler import Handler
from app.models.handler_affiliations import HandlerAffiliation


def user_has_role(current_user: User, role_name: str) -> bool:
    wanted = role_name.strip().lower()
    roles = getattr(current_user, "roles", []) or []
    return any(
        (getattr(r, "role_name", "") or "").strip().lower() == wanted
        for r in roles
    )


def get_affiliation_scope(db: Session, current_user: User) -> Optional[Set[int]]:
    # print("---- get_affiliation_scope ----")
    # print("user_id:", current_user.user_id)
    # print("roles:", [getattr(r, "role_name", None) for r in (current_user.roles or [])])

    if user_has_role(current_user, "admin"):
        return None

    if not user_has_role(current_user, "supervisor"):
        return set()

    handler = (
        db.query(Handler)
        .filter(Handler.user_id == current_user.user_id)
        .first()
    )
    # print("handler:", getattr(handler, "handler_id", None))

    if not handler:
        return set()

    rows = (
        db.query(HandlerAffiliation.affiliation_id)
        .filter(
            HandlerAffiliation.handler_id == handler.handler_id,
            HandlerAffiliation.ended_at.is_(None),
        )
        .all()
    )

    scope = {row[0] for row in rows if row[0] is not None}
    # print("scope rows:", rows)
    # print("scope set:", scope)
    return scope


def require_supervisor_or_admin(db: Session, current_user: User) -> Optional[Set[int]]:
    scope = get_affiliation_scope(db, current_user)

    if scope is None:
        return None

    if not user_has_role(current_user, "supervisor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized",
        )

    if not scope:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No affiliation scope assigned",
        )

    return scope


def scope_users_query(query: Query, db: Session, current_user: User) -> Query:
    scope = get_affiliation_scope(db, current_user)

    if scope is None:
        return query

    if not scope:
        return query.filter(False)

    return (
        query.join(Handler, Handler.user_id == User.user_id)
        .join(
            HandlerAffiliation,
            HandlerAffiliation.handler_id == Handler.handler_id,
        )
        .filter(
            HandlerAffiliation.affiliation_id.in_(scope),
            HandlerAffiliation.ended_at.is_(None),
        )
        .distinct()
    )

def scope_handlers_query(query: Query, db: Session, current_user: User) -> Query:
    scope = get_affiliation_scope(db, current_user)

    if scope is None:
        return query

    if not scope:
        return query.filter(False)

    return (
        query.join(
            HandlerAffiliation,
            HandlerAffiliation.handler_id == Handler.handler_id,
        )
        .filter(
            HandlerAffiliation.affiliation_id.in_(scope),
            HandlerAffiliation.ended_at.is_(None),
        )
        .distinct()
    )