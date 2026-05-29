from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Tuple, Optional
from app.utils.auth import user_has_role
from sqlalchemy.orm import Session, joinedload, contains_eager
from sqlalchemy import false, func, or_

from app.models.discipline import Discipline
from app.models.standard import Standard
from app.models.certification import Certification
from app.models.team import Team
from app.models.user import User
from app.models.handler import Handler   # adjust if your module name differs
from app.models.dog import Dog           # adjust if your module name differs
from app.models.handler_affiliations import HandlerAffiliation

def _get_attr(obj: Any, *names: str, default: Any = None) -> Any:
    """
    Try a list of attribute or dict keys, return the first non-None one.
    """
    if obj is None:
        return default

    for name in names:
        if not name:
            continue

        # attrs
        if hasattr(obj, name):
            val = getattr(obj, name)
            if val is not None:
                return val

        # dict
        if isinstance(obj, dict) and name in obj:
            val = obj[name]
            if val is not None:
                return val

    return default


def _normalize_status(raw_status: Any) -> str:
    """
    Accepts:
      - None
      - a string
      - an Enum-like object with a .value attribute
    Returns a lowercase string.
    """
    if raw_status is None:
        return ""

    # Enum-like
    if hasattr(raw_status, "value"):
        raw_status = raw_status.value

    if not isinstance(raw_status, str):
        raw_status = str(raw_status)

    return raw_status.strip().lower()


def _determine_status(cert: Certification) -> str:
    """
    Decide the matrix status label for a certification.

    Rules:
      1. Preserve explicit workflow/business statuses from the DB.
      2. Only decorate ACTIVE with expiring/expired based on expires_at.
      3. Never convert INCOMPLETE into ACTIVE.
    """
    today = date.today()

    raw_status = getattr(cert, "status", None)
    s = _normalize_status(raw_status)

    # revoked always wins
    if s.startswith("revok"):
        return "revoked"

    # preserve explicit DB statuses
    if s in {"pending", "incomplete", "suspended", "rejected"}:
        return s

    # only decorate active-like statuses by expiration
    if s in {"active", "expired", ""}:
        expires = getattr(cert, "expires_at", None)
        if expires:
            exp_date = expires.date() if hasattr(expires, "date") else expires
            if exp_date < today:
                return "expired"
            days = (exp_date - today).days
            if days <= 60:
                return "expiring"
            return "active"
        return "active"

    # fallback: preserve unknown statuses rather than lying
    return s or "active"


def _choose_better_cert(a: Certification, b: Certification) -> Certification:
    a_awarded = getattr(a, "date_awarded", None)
    b_awarded = getattr(b, "date_awarded", None)

    if a_awarded and b_awarded:
        return b if b_awarded >= a_awarded else a
    if a_awarded and not b_awarded:
        return a
    if b_awarded and not a_awarded:
        return b

    # tie-breaker: later expires_at wins (optional but useful)
    a_expires = getattr(a, "expires_at", None)
    b_expires = getattr(b, "expires_at", None)
    if a_expires and b_expires:
        return a if a_expires >= b_expires else b
    if a_expires and not b_expires:
        return a
    if b_expires and not a_expires:
        return b

    return a

def _discipline_group_ids_for_user(u: User) -> set[int]:
    groups = getattr(u, "discipline_groups", None)
    if not isinstance(groups, list):
        return set()

    out: set[int] = set()
    for g in groups:
        try:
            group_id = None
            if isinstance(g, dict):
                group_id = g.get("group_id")
            else:
                group_id = getattr(g, "group_id", None)

            if group_id is not None:
                out.add(int(group_id))
        except Exception:
            pass

    return out


def build_certification_matrix(db: Session, current_user: User, affiliation_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Build a matrix of teams (rows) vs disciplines (columns).
    Adds certification.location + supervisor full name.
    """

    # 1) Disciplines (column headers)
    disciplines: List[Discipline] = (
        db.query(Discipline)
        .order_by(Discipline.sortorder.asc(), Discipline.name.asc())
        .filter(Discipline.show_operational == True)  # noqa: E712
        .all()
    )

    is_admin = user_has_role(current_user, "admin")
    cu_id = getattr(current_user, "user_id", None)

    discipline_names: List[str] = [d.name for d in disciplines]
    disc_id_to_name: Dict[int, str] = {int(d.discipline_id): d.name for d in disciplines}
    disc_name_to_id: Dict[str, int] = {d.name: int(d.discipline_id) for d in disciplines}

    disc_id_to_group_id: Dict[int, int] = {}
    disc_name_to_group_id: Dict[str, int] = {}

    for d in disciplines:
        disc_id = getattr(d, "discipline_id", None)
        group_id = getattr(d, "group_id", None)
        name = getattr(d, "name", None)

        if disc_id is not None and group_id is not None:
            disc_id_to_group_id[int(disc_id)] = int(group_id)

        if name and group_id is not None:
            disc_name_to_group_id[str(name)] = int(group_id)

    # 1b) Determine applicable standard per discipline (latest effective_date <= today)
    today = date.today()
    aallowed_group_ids = _discipline_group_ids_for_user(current_user)

    standards: List[Standard] = (
        db.query(Standard)
        .filter(Standard.effective_date <= today)
        .order_by(Standard.discipline_id, Standard.effective_date.desc())
        .all()
    )

    applicable_std_by_disc_name: Dict[str, int] = {}
    seen_disc_ids: set[int] = set()

    for s in standards:
        disc_id = getattr(s, "discipline_id", None)
        std_id = getattr(s, "standard_id", None)
        if disc_id is None or std_id is None:
            continue

        disc_id = int(disc_id)
        if disc_id in seen_disc_ids:
            continue
        seen_disc_ids.add(disc_id)

        disc_name = disc_id_to_name.get(disc_id)
        if disc_name:
            applicable_std_by_disc_name[disc_name] = int(std_id)

    # 2) Teams + handler.user + dog eager-loaded
    teams = (
        db.query(Team)
        .join(Team.handler)          # Team -> Handler
        .join(Handler.user)          # Handler -> User
        .options(
            contains_eager(Team.handler).contains_eager(Handler.user),
            joinedload(Team.dog),
        )
        .filter(
            Team.status == "active",
            Handler.status == "active",
            User.is_active == True,  # noqa: E712
        )
    )
            # Optional affiliation filter (handler has active membership)
        # ✅ affiliation filter
    if affiliation_id is not None:
        teams = teams.join(
            HandlerAffiliation,
            (HandlerAffiliation.handler_id == Handler.handler_id)
            & (HandlerAffiliation.affiliation_id == affiliation_id)
            & (HandlerAffiliation.ended_at.is_(None)),
        ).distinct(Team.team_id)

    teams = teams.all()
        

    # 3) All certifications joined to their standards & disciplines
    team_ids = [t.team_id for t in teams]
    if not team_ids:
        return {
            "disciplines": discipline_names,
            "standard_ids_by_discipline": applicable_std_by_disc_name,
            "teams": [],
        }

    # cert_rows = (
    #     db.query(Certification, Standard, Discipline)
    #     .join(Standard, Certification.standard_id == Standard.standard_id)
    #     .join(Discipline, Standard.discipline_id == Discipline.discipline_id)
    #     .filter(Certification.team_id.in_(team_ids))
    #     .all()
    # )

    today = date.today()

    latest_cert_ids = (
        db.query(
            Certification.team_id.label("team_id"),
            Certification.standard_id.label("standard_id"),
            func.max(Certification.certification_id).label("certification_id"),
        )
        .filter(Certification.team_id.in_(team_ids))
        .filter(
            or_(
                Certification.expires_at.is_(None),
                Certification.expires_at >= today,
            )
        )
        .filter(Certification.status != "revoked")
        .group_by(Certification.team_id, Certification.standard_id)
        .subquery()
    )

    cert_rows = (
        db.query(Certification, Standard, Discipline)
        .join(
            latest_cert_ids,
            latest_cert_ids.c.certification_id == Certification.certification_id,
        )
        .join(Standard, Certification.standard_id == Standard.standard_id)
        .join(Discipline, Standard.discipline_id == Discipline.discipline_id)
        .all()
    )

    # (team_id, discipline_name) -> best Certification
    best_cert_by_team_disc: Dict[Tuple[int, str], Certification] = {}

    for cert, std, disc in cert_rows:
        disc_name = disc_id_to_name.get(int(disc.discipline_id), disc.name)

        team_id = getattr(cert, "team_id", None)
        if team_id is None:
            continue

        key = (int(team_id), disc_name)
        existing = best_cert_by_team_disc.get(key)
        if existing is None:
            best_cert_by_team_disc[key] = cert
        else:
            best_cert_by_team_disc[key] = _choose_better_cert(existing, cert)

    # 3b) Build supervisor_id -> "First Last" map for any supervisors present
    supervisor_ids: set[int] = set()
    for cert in best_cert_by_team_disc.values():
        sid = getattr(cert, "supervisor_id", None)
        if sid is not None:
            try:
                supervisor_ids.add(int(sid))
            except Exception:
                pass

    supervisor_name_by_id: Dict[int, str] = {}
    if supervisor_ids:
        sup_users: List[User] = (
            db.query(User)
            .filter(User.user_id.in_(list(supervisor_ids)))
            .all()
        )
        for u in sup_users:
            first = (getattr(u, "first_name", "") or "").strip()
            last = (getattr(u, "last_name", "") or "").strip()
            full = (f"{first} {last}").strip()
            supervisor_name_by_id[int(u.user_id)] = full

    # 3c) Build last_actor_user_id -> "First Last" map for any actors present
    last_actor_ids: set[int] = set()
    for cert in best_cert_by_team_disc.values():
        aid = getattr(cert, "last_actor_user_id", None)
        if aid is not None:
            try:
                last_actor_ids.add(int(aid))
            except Exception:
                pass

    last_actor_name_by_id: Dict[int, str] = {}
    if last_actor_ids:
        actor_users: List[User] = (
            db.query(User)
            .filter(User.user_id.in_(list(last_actor_ids)))
            .all()
        )
        for u in actor_users:
            first = (getattr(u, "first_name", "") or "").strip()
            last = (getattr(u, "last_name", "") or "").strip()
            full = (f"{first} {last}").strip()
            last_actor_name_by_id[int(u.user_id)] = full

    # 3d) Build co_evaluator_user_id -> "First Last" map for any co-evaluators present
    co_evaluator_ids: set[int] = set()
    for cert in best_cert_by_team_disc.values():
        eid = getattr(cert, "co_evaluator_user_id", None)
        if eid is not None:
            try:
                co_evaluator_ids.add(int(eid))
            except Exception:
                pass

    co_evaluator_name_by_id: Dict[int, str] = {}
    if co_evaluator_ids:
        co_eval_users: List[User] = (
            db.query(User)
            .filter(User.user_id.in_(list(co_evaluator_ids)))
            .all()
        )
        for u in co_eval_users:
            first = (getattr(u, "first_name", "") or "").strip()
            last = (getattr(u, "last_name", "") or "").strip()
            full = (f"{first} {last}").strip()
            co_evaluator_name_by_id[int(u.user_id)] = full

    # 4) Build final DTO
    result_teams: List[Dict[str, Any]] = []

    for team in teams:
        team_id = int(_get_attr(team, "id", "team_id", default=0))

        # Handler
        handler = _get_attr(team, "handler", default=None)
        handler_first = ""
        handler_last = ""

        if handler is not None:
            user = _get_attr(handler, "user", default=None)
            if user is not None:
                handler_first = (
                    _get_attr(user, "first_name", "firstname", "given_name", "name", default="") or ""
                )
                handler_last = (
                    _get_attr(user, "last_name", "lastname", "surname", default="") or ""
                )
            else:
                handler_first = (
                    _get_attr(handler, "first_name", "firstname", "given_name", "name", default="") or ""
                )
                handler_last = (
                    _get_attr(handler, "last_name", "lastname", "surname", default="") or ""
                )
        else:
            handler_first = _get_attr(team, "handler_first", "first_name", default="") or ""
            handler_last = _get_attr(team, "handler_last", "last_name", default="") or ""

        # Dog
        dog = _get_attr(team, "dog", default=None)
        if dog is not None:
            dog_name = (_get_attr(dog, "call_name", "name", "dog_name", default="") or "")
        else:
            dog_name = _get_attr(team, "dog_name", default="") or ""

        # Owner = handler's user_id (compute once per team)
        handler_user_id = None
        if handler is not None:
            try:
                direct_uid = _get_attr(handler, "user_id", default=None)
                if direct_uid is not None:
                    handler_user_id = int(direct_uid)
            except Exception:
                handler_user_id = None

            if handler_user_id is None:
                user = _get_attr(handler, "user", default=None)
                if user is not None:
                    try:
                        handler_user_id = int(_get_attr(user, "user_id", "id", default=None))
                    except Exception:
                        handler_user_id = None

        # compute once per team
        team_is_owner = bool(
            cu_id is not None
            and handler_user_id is not None
            and int(cu_id) == int(handler_user_id)
        )


        raw_groups = getattr(current_user, "discipline_groups", []) or []

        user_group_ids = set()
        for g in raw_groups:
            try:
                gid = g.get("group_id") if isinstance(g, dict) else getattr(g, "group_id", None)
                if gid is not None:
                    user_group_ids.add(int(gid))
            except Exception:
                pass

        # Certifications for each discipline
        team_certs: Dict[str, Dict[str, Any]] = {}

        for disc_name in discipline_names:
            key = (team_id, disc_name)
            cert = best_cert_by_team_disc.get(key)

            if cert is None:
                team_certs[disc_name] = {
                    "discipline_id": disc_name_to_id.get(disc_name),
                    # "status": "none",
                    # "certification_id": None,
                    "standard_id": applicable_std_by_disc_name.get(disc_name),
                    "has_prior_cert_for_discipline": False,
                    # needed for add-cert / ownership UI
                    "is_owner": team_is_owner,
                    # "can_view": False,
                }
                continue

            status = _determine_status(cert)
            expires = getattr(cert, "expires_at", None)
            date_awarded = getattr(cert, "date_awarded", None)

            location = getattr(cert, "location", None)
            comment = getattr(cert, "comment", None)
            supervisor_id = getattr(cert, "supervisor_id", None)
            supervisor_id_int: Optional[int] = None
            supervisor_name: Optional[str] = None

            last_actor_user_id = getattr(cert, "last_actor_user_id", None)
            last_actor_user_id_int: Optional[int] = None
            last_actor_name: Optional[str] = None

            requires_co_evaluator = bool(getattr(cert, "requires_co_evaluator", False))
            co_evaluator_user_id = getattr(cert, "co_evaluator_user_id", None)
            co_evaluator_user_id_int: Optional[int] = None
            co_evaluator_name: Optional[str] = None
            co_evaluated_at = getattr(cert, "co_evaluated_at", None)
            co_evaluator_note = getattr(cert, "co_evaluator_note", None)

            if supervisor_id is not None:
                try:
                    supervisor_id_int = int(supervisor_id)
                    supervisor_name = supervisor_name_by_id.get(supervisor_id_int)
                except Exception:
                    supervisor_id_int = None
                    supervisor_name = None

            if last_actor_user_id is not None:
                try:
                    last_actor_user_id_int = int(last_actor_user_id)
                    last_actor_name = last_actor_name_by_id.get(last_actor_user_id_int)
                except Exception:
                    last_actor_user_id_int = None
                    last_actor_name = None

            if co_evaluator_user_id is not None:
                try:
                    co_evaluator_user_id_int = int(co_evaluator_user_id)
                    co_evaluator_name = co_evaluator_name_by_id.get(co_evaluator_user_id_int)
                except Exception:
                    co_evaluator_user_id_int = None
                    co_evaluator_name = None

            # Owner = handler's user_id (already joined!)
            handler_user_id = None
            if handler is not None:
                try:
                    direct_uid = _get_attr(handler, "user_id", default=None)
                    if direct_uid is not None:
                        handler_user_id = int(direct_uid)
                except Exception:
                    handler_user_id = None

                if handler_user_id is None:
                    user = _get_attr(handler, "user", default=None)
                    if user is not None:
                        try:
                            handler_user_id = int(_get_attr(user, "user_id", "id", default=None))
                        except Exception:
                            handler_user_id = None

            # Supervisor = cert.supervisor_id
            supervisor_user_id = supervisor_id_int

            # Evaluator authority is determined by the discipline group, not standard_id.
            cell_group_id = disc_name_to_group_id.get(disc_name)


            is_owner = bool(
                cu_id is not None
                and handler_user_id is not None
                and int(cu_id) == int(handler_user_id)
            )

            can_eval_this_group = bool(
                cell_group_id is not None
                and int(cell_group_id) in user_group_ids
            )

            # print("GROUP DEBUG", {
            #     "cell_group_id": cell_group_id,
            #     "user_group_ids": sorted(user_group_ids),
            # })
            # print(current_user.discipline_groups)

            can_issue_or_modify = bool(
                is_admin
                or (can_eval_this_group and not is_owner)
            )

            is_supervisor = bool(
                cu_id is not None
                and supervisor_user_id is not None
                and int(cu_id) == int(supervisor_user_id)
            )

            can_view = bool(
                is_admin
                or is_owner
                or is_supervisor
                or can_eval_this_group
            )

            # print("CO-EVAL DEBUG", {
            #     "user_id": cu_id,
            #     "disc_name": disc_name,
            #     "cell_group_id": cell_group_id,
            #     "allowed_group_ids": sorted(list(user_group_ids)),
            #     "status": status,
            #     "requires_co_evaluator": requires_co_evaluator,
            #     "co_evaluator_user_id": co_evaluator_user_id_int,
            #     "is_owner": is_owner,
            #     "is_supervisor": is_supervisor,
            #     "can_eval_this_group": can_eval_this_group,
            # })

            can_co_evaluate = bool(
                status == "pending"
                and requires_co_evaluator
                and co_evaluator_user_id_int is None
                and not is_owner
                and not is_supervisor
                and can_eval_this_group
            )

            can_owner_manage = bool(
                is_admin
                or is_owner
            )

            can_revoke = bool(can_owner_manage and status != "revoked")
            can_suspend = bool(can_owner_manage and status == "active")
            can_unsuspend = bool(can_owner_manage and status == "suspended")

            can_issue_or_modify = bool(
                is_admin
                or (can_eval_this_group and not is_owner)
            )

            team_certs[disc_name] = {
                "discipline_id": disc_name_to_id.get(disc_name),
                "status": status,
                "expires": expires.isoformat() if expires else None,
                "certification_id": getattr(cert, "certification_id", None),
                "standard_id": applicable_std_by_disc_name.get(disc_name),
                "date_awarded": date_awarded.isoformat() if date_awarded else None,
                "location": location,
                "comment": comment,
                "supervisor_id": supervisor_id_int,
                "last_actor_user_id": last_actor_user_id_int,
                "supervisor_name": supervisor_name,
                "last_actor_name": last_actor_name,
                "has_prior_cert_for_discipline": True,

                "evaluation_complete": getattr(cert, "evaluation_complete", True),
                "requires_co_evaluator": requires_co_evaluator,
                "co_evaluator_user_id": co_evaluator_user_id_int,
                "co_evaluator_name": co_evaluator_name,
                "co_evaluated_at": co_evaluated_at.isoformat() if co_evaluated_at else None,
                "co_evaluator_note": co_evaluator_note,
                "can_co_evaluate": can_co_evaluate,

                "is_owner": team_is_owner,
                "can_view": can_view,
                "can_revoke": can_revoke,
                "can_suspend": can_suspend,
                "can_unsuspend": can_unsuspend,
            }

        result_teams.append(
            {
                "team_id": team_id,
                "handler_first": handler_first,
                "handler_last": handler_last,
                "dog_name": dog_name,
                "certifications": team_certs,
            }
        )

    return {
        "disciplines": discipline_names,
        "standard_ids_by_discipline": applicable_std_by_disc_name,
        "teams": result_teams,
    }
