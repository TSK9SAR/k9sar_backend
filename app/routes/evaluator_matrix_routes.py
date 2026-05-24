from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, or_
from app.database import get_db
from app.utils.auth import get_current_user, require_mfa_verified, require_admin

from app.schemas.evaluator_matrix_schema import EvaluatorMatrixOut, EvaluatorGroupOut, EvaluatorUserRowOut, EvaluatorCellOut 
from math import radians, sin, cos, sqrt, atan2
from typing import Optional, List
from app.models.user import User
from app.models.certification import Certification
from app.models.team import Team
from app.models.handler import Handler
from app.models.standard import Standard
from app.models.discipline import Discipline
from app.models.discipline_group import DisciplineGroup
from app.models.user_discipline_group import user_discipline_groups  # association table
# from app.models.evaluator_candidate_seed import EvaluatorCandidateSeed

router = APIRouter(prefix="/evaluators", tags=["Evaluators"])

def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.7613  # miles
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c

from datetime import date
from dateutil.relativedelta import relativedelta
from sqlalchemy import select, distinct

from datetime import date
from dateutil.relativedelta import relativedelta
from sqlalchemy import select, distinct, and_

def has_signature(u: User) -> bool:
    return bool((getattr(u, "signature_url", None) or "").strip())

def get_computed_candidate_pairs(db: Session) -> set[tuple[int, int]]:
    cutoff = date.today() - relativedelta(years=5)
    today = date.today()

    # Has at least one certification in the group awarded 5+ years ago
    historical_rows = db.execute(
        select(
            distinct(Handler.user_id),
            Discipline.group_id,
        )
        .select_from(Certification)
        .join(Team, Team.team_id == Certification.team_id)
        .join(Handler, Handler.handler_id == Team.handler_id)
        .join(Standard, Standard.standard_id == Certification.standard_id)
        .join(Discipline, Discipline.discipline_id == Standard.discipline_id)
        .where(Handler.user_id.isnot(None))
        .where(Discipline.group_id.isnot(None))
        .where(Certification.date_awarded.isnot(None))
        .where(Certification.date_awarded <= cutoff)
    ).all()

    historical_pairs = {
        (int(user_id), int(group_id))
        for user_id, group_id in historical_rows
    }

    # Is currently certified in at least one discipline in the same group
    current_rows = db.execute(
        select(
            distinct(Handler.user_id),
            Discipline.group_id,
        )
        .select_from(Certification)
        .join(Team, Team.team_id == Certification.team_id)
        .join(Handler, Handler.handler_id == Team.handler_id)
        .join(Standard, Standard.standard_id == Certification.standard_id)
        .join(Discipline, Discipline.discipline_id == Standard.discipline_id)
        .where(Handler.user_id.isnot(None))
        .where(Discipline.group_id.isnot(None))
        .where(Certification.status == "active")  # adjust if stored differently
        .where(Certification.expires_at.isnot(None))
        .where(Certification.expires_at >= today)
    ).all()

    current_pairs = {
        (int(user_id), int(group_id))
        for user_id, group_id in current_rows
    }

    print("HISTORICAL PAIRS:", len(historical_pairs), list(historical_pairs)[:20])
    print("CURRENT PAIRS:", len(current_pairs), list(current_pairs)[:20])
    print("INTERSECTION:", len(historical_pairs & current_pairs), list(historical_pairs & current_pairs)[:20])

    return historical_pairs & current_pairs


def get_effective_candidate_pairs(db: Session) -> set[tuple[int, int]]:
    computed = get_computed_candidate_pairs(db)

    evaluator_rows = db.execute(
        select(
            user_discipline_groups.c.user_id,
            user_discipline_groups.c.group_id,
        )
    ).all()
    evaluators = {(int(user_id), int(group_id)) for user_id, group_id in evaluator_rows}

    return computed - evaluators

@router.get("/matrix", response_model=EvaluatorMatrixOut)
def get_evaluator_matrix(
    q: Optional[str] = None,
    group_ids: List[int] = Query(default=[]),
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    radius_mi: Optional[float] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    # Any logged-in user can view

    groups = (
        db.query(DisciplineGroup)
        .order_by(DisciplineGroup.sortorder, DisciplineGroup.name)
        .filter(DisciplineGroup.name != "Legacy")
        .filter(DisciplineGroup.show_operational == True)  # noqa: E712
        .all()
    )
    group_id_list = [g.group_id for g in groups]

    # ---------------------------------
    # Real evaluator memberships
    # ---------------------------------
    pairs = db.execute(
        select(user_discipline_groups.c.user_id, user_discipline_groups.c.group_id)
        .select_from(
            user_discipline_groups.join(
                User, User.user_id == user_discipline_groups.c.user_id
            )
        )
        .where(User.is_active == True)
    ).all()

    member_map: dict[int, set[int]] = {}
    for user_id, group_id in pairs:
        member_map.setdefault(int(user_id), set()).add(int(group_id))

    # ---------------------------------
    # Candidate memberships (advisory only)
    # ---------------------------------
    candidate_pairs = get_effective_candidate_pairs(db)

    print("CANDIDATE PAIRS COUNT:", len(candidate_pairs))
    print("CANDIDATE PAIRS SAMPLE:", list(candidate_pairs)[:20])

    candidate_map: dict[int, dict[int, str]] = {}

    for user_id, group_id in candidate_pairs:
        candidate_map.setdefault(int(user_id), {})[int(group_id)] = "computed"

    print("CANDIDATE MAP COUNT:", len(candidate_map))


    # ---------------------------------
    # Base users query
    # ---------------------------------
    uq = db.query(User).filter(User.is_active == True)

    if q:
        term = f"%{q.strip()}%"
        uq = uq.filter(
            or_(
                User.email.ilike(term),
                User.first_name.ilike(term),
                User.last_name.ilike(term),
            )
        )

    users = uq.order_by(User.last_name, User.first_name, User.email).all()

    out_groups = [
        EvaluatorGroupOut(
            group_id=g.group_id,
            name=g.name,
            sortorder=getattr(g, "sortorder", 0) or 0,
        )
        for g in groups
    ]

    out_users: list[EvaluatorUserRowOut] = []

    for u in users:
        user_groups = member_map.get(u.user_id, set())
        user_candidates = candidate_map.get(u.user_id, set())

        user_candidates = set(candidate_map.get(u.user_id, {}).keys())

        signature_url = (getattr(u, "signature_url", None) or "").strip()
        user_missing_signature = not signature_url

        if u.user_id == 50:
            print("USER 50 signature_url:", repr(signature_url))
            print("USER 50 missing_signature:", user_missing_signature)

        # Group filter: keep users who are evaluator OR candidate in any selected group_ids
        if group_ids:
            if not any((gid in user_groups) or (gid in user_candidates) for gid in group_ids):
                continue

        distance_mi = None
        if lat is not None and lng is not None:
            u_lat = getattr(u, "domicile_lat", None)
            u_lng = getattr(u, "domicile_lng", None)
            if u_lat is not None and u_lng is not None:
                distance_mi = round(haversine_miles(lat, lng, float(u_lat), float(u_lng)), 1)

                if radius_mi is not None and distance_mi > float(radius_mi):
                    continue
            else:
                if radius_mi is not None:
                    continue

        memberships = {
            gid: EvaluatorCellOut(
                is_evaluator=(gid in user_groups),
                is_candidate=(gid in user_candidates),
                candidate_source=candidate_map.get(u.user_id, {}).get(gid),
            )
            for gid in group_id_list
        }

        out_users.append(
            EvaluatorUserRowOut(
                user_id=u.user_id,
                first_name=u.first_name,
                last_name=u.last_name,
                email=u.email,
                phone=getattr(u, "phone", None),
                distance_mi=distance_mi,
                evaluator_missing_signature=user_missing_signature,
                memberships=memberships,
            )
        )

    return EvaluatorMatrixOut(groups=out_groups, users=out_users)

@router.patch("/matrix/toggle")
def toggle_evaluator_membership(
    user_id: int,
    group_id: int,
    enabled: bool,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
    _mfa=Depends(require_mfa_verified),  # <-- add this
):

    # Validate existence
    g = db.query(DisciplineGroup).filter(DisciplineGroup.group_id == group_id).first()
    if not g:
        raise HTTPException(status_code=404, detail="Discipline group not found")
    u = db.query(User).filter(User.user_id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    exists = db.execute(
        select(user_discipline_groups.c.user_id)
        .where(
            user_discipline_groups.c.user_id == user_id,
            user_discipline_groups.c.group_id == group_id,
        )
    ).first()

    if enabled and not exists:
        db.execute(user_discipline_groups.insert().values(user_id=user_id, group_id=group_id))
        db.commit()
    elif (not enabled) and exists:
        db.execute(
            user_discipline_groups.delete().where(
                user_discipline_groups.c.user_id == user_id,
                user_discipline_groups.c.group_id == group_id,
            )
        )
        db.commit()

    return {"ok": True, "user_id": user_id, "group_id": group_id, "enabled": enabled}
