# app/routes/public_routes.py

from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.models.public_portal_event import PublicPortalEvent
from app.database import get_db
from app.models import Team, Handler, User, Certification, Standard, Discipline, Dog
from app.utils.geolocation import haversine
from app.models.handler_affiliations import HandlerAffiliation
from app.services.auth_activity import get_real_client_ip

from app.schemas.public_schema import (
    PublicMatrixResponse,
    PublicPortalTrackIn,
    PublicTeamRow,
    PublicActiveCert,
    PublicStandardOut,
)

router = APIRouter(prefix="/public", tags=["public"])

today = date.today()

def _mm_yy(d: Optional[date]) -> Optional[str]:
    if not d:
        return None
    return f"{d.month:02d}/{str(d.year)[-2:]}"


def _as_date(v) -> Optional[date]:
    """Convert DB value (date/datetime/str/None) safely to date or None."""
    if v is None:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str):
        # Handle MySQL "0000-00-00" / bad strings defensively
        if v.startswith("0000-00-00"):
            return None
        try:
            # accepts "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS"
            return datetime.fromisoformat(v.replace("Z", "")).date()
        except Exception:
            return None
    return None


def log_public_event(
    db: Session,
    request: Request,
    section: str,
    session_id: str | None = None,
):
    db.add(
        PublicPortalEvent(
            section=section,
            session_id=session_id,
            ip_address=get_real_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            referer=request.headers.get("referer"),
        )
    )
    db.commit()

@router.get("/matrix", response_model=PublicMatrixResponse)
def public_matrix(
    q: Optional[str] = Query(None, description="Search handler or dog name"),
    discipline: Optional[List[str]] = Query(
        None, description="Repeatable discipline name filter"
    ),
    affiliation_id: Optional[int] = Query(None, description="Filter teams by handler's active affiliation_id"),
    lat: Optional[float] = Query(None),
    lng: Optional[float] = Query(None),
    radius_km: Optional[float] = Query(None, ge=0),
    radius_mi: Optional[float] = Query(None, ge=0),
    db: Session = Depends(get_db),
):
    """
    Public certification directory:
      - Teams with at least one ACTIVE certification
      - Returns handler, dog, contact, and active cert expiry (MM/YY)
      - Optional discipline filter
      - Optional distance filter (km preferred, mi accepted)
    """

    # -----------------------------
    # 1) Decide effective radius (km)
    # -----------------------------
    radius_km_effective: Optional[float] = None
    if radius_km is not None:
        radius_km_effective = radius_km
    elif radius_mi is not None:
        radius_km_effective = radius_mi * 1.609344

    has_geo = (
        lat is not None
        and lng is not None
        and radius_km_effective is not None
        and radius_km_effective > 0
    )

    # -----------------------------
    # 2) Base query: Team + Handler + User + Dog
    # -----------------------------
    base = (
        db.query(Team, Handler, User, Dog)
        .join(Handler, Team.handler_id == Handler.handler_id)
        .join(User, Handler.user_id == User.user_id)
        .join(Dog, Team.dog_id == Dog.dog_id)
    )

    if affiliation_id is not None:
        base = base.join(
            HandlerAffiliation,
            (HandlerAffiliation.handler_id == Handler.handler_id)
            & (HandlerAffiliation.affiliation_id == affiliation_id)
            & (HandlerAffiliation.ended_at.is_(None)),
        )

    if q:
        q_like = f"%{q.strip()}%"
        full_name = (User.first_name + " " + User.last_name)
        base = base.filter(
            or_(
                User.first_name.ilike(q_like),
                User.last_name.ilike(q_like),
                full_name.ilike(q_like),
                Dog.name.ilike(q_like),
            )
        )

    # Ensure unique teams
    base = base.distinct(Team.team_id)

    # Only show active teams with active handlers/users
    base = base.filter(
        Team.status == "active",
        Handler.status == "active",
        User.is_active.is_(True),
    )

    team_rows = base.all()
    if not team_rows:
        return PublicMatrixResponse(disciplines=[], teams=[])

    team_ids = [t.team_id for (t, _h, _u, _d) in team_rows]
    if not team_ids:
        return PublicMatrixResponse(disciplines=[], teams=[])

    # Normalize discipline filter: strip, drop blanks
    discipline_names: Optional[List[str]] = None
    if discipline:
        discipline_names = [d.strip() for d in discipline if d and d.strip()]
        if not discipline_names:
            discipline_names = None

    # -----------------------------
    # 3) ACTIVE cert rows (team_id, expires_at, cert_id, discipline_name, discipline_sortorder)
    #    + ordered, pruned discipline header list (by sortorder)
    # -----------------------------
    base_filters = [
        Certification.team_id.in_(team_ids),
        Certification.status == "active",
        Certification.expires_at.isnot(None),
        Certification.expires_at >= today,
    ]
    if discipline_names:
        base_filters.append(Discipline.name.in_(discipline_names))

    cert_rows = (
        db.query(
            Certification.team_id,
            Certification.expires_at,
            Certification.certification_id,
            Discipline.name.label("discipline_name"),
            Discipline.sortorder.label("discipline_sortorder"),
        )
        .join(Standard, Certification.standard_id == Standard.standard_id)
        .join(Discipline, Standard.discipline_id == Discipline.discipline_id)
        .filter(*base_filters)
        .filter(Discipline.show_operational == True)  # noqa: E712
        .order_by(
            Discipline.sortorder.asc(),
            Discipline.name.asc(),
            Certification.team_id.asc(),
            Certification.certification_id.asc(),
        )
        .all()
    )

    if not cert_rows:
        return PublicMatrixResponse(disciplines=[], teams=[])

    # Disciplines list must be pruned to what exists AFTER filters, but still ordered by sortorder.
    # Use a stable subquery of discipline_id, then join back to Discipline for ordering.
    disc_ids_subq = (
        db.query(Standard.discipline_id.label("discipline_id"))
        .join(Certification, Certification.standard_id == Standard.standard_id)
        .join(Discipline, Standard.discipline_id == Discipline.discipline_id)
        .filter(*base_filters)
        .distinct()
        .subquery()
    )

    disciplines_sorted = [
        r[0]
        for r in (
            db.query(Discipline.name)
            .join(disc_ids_subq, disc_ids_subq.c.discipline_id == Discipline.discipline_id)
            .order_by(Discipline.sortorder.asc(), Discipline.name.asc())
            .all()
        )
    ]

    # -----------------------------
    # 4) Deduplicate: keep the latest expires_at per (team_id, discipline_name)
    # -----------------------------
    latest: Dict[Tuple[int, str], Tuple[int, date]] = {}
    # key -> (certification_id, expires_at_date)
    for team_id, expires_at, cert_id, disc_name, _disc_sortorder in cert_rows:
        exp_date = _as_date(expires_at)
        if exp_date is None:
            continue

        if (exp_date < today) or (disc_name is None):
            continue

        key = (team_id, disc_name)
        prev = latest.get(key)
        if prev is None or exp_date >= prev[1]:
            latest[key] = (cert_id, exp_date)

    # Build per-team cert list
    certs_by_team: Dict[int, List[PublicActiveCert]] = {}
    for (team_id, disc_name), (cert_id, exp_date) in latest.items():
        certs_by_team.setdefault(team_id, []).append(
            PublicActiveCert(
                discipline=disc_name,
                expires_mm_yy=_mm_yy(exp_date),
                certification_id=cert_id,
            )
        )

    # IMPORTANT: do NOT alphabetize here; use Discipline.sortorder order
    # Sort chips to match disciplines_sorted order
    order_index = {name: i for i, name in enumerate(disciplines_sorted)}
    for team_id in certs_by_team:
        certs_by_team[team_id].sort(
            key=lambda c: (order_index.get(c.discipline, 10**9), (c.discipline or "").lower())
        )

    # -----------------------------
    # 5) Assemble teams output + optional distance filter
    # -----------------------------
    teams_out: List[PublicTeamRow] = []

    for (t, _h, u, d) in team_rows:
        active_certs = certs_by_team.get(t.team_id)
        if not active_certs:
            # only public teams with at least one active cert (after discipline filter)
            continue

        # Distance filter (km)
        distance_km_val: Optional[float] = None
        if has_geo:
            if u.domicile_lat is None or u.domicile_lng is None:
                continue

            distance_km_val = haversine(lat, lng, u.domicile_lat, u.domicile_lng)
            if distance_km_val > radius_km_effective:
                continue

        row = PublicTeamRow(
            team_id=t.team_id,
            handler_full_name=f"{u.first_name} {u.last_name}",
            email=u.email,
            phone=u.phone,
            dog_name=d.name,
            active_certs=active_certs,
        )

        if distance_km_val is not None:
            row.distance_km = round(distance_km_val, 1)
            row.distance_mi = round(distance_km_val / 1.609344, 1)

        teams_out.append(row)

    if not teams_out:
        return PublicMatrixResponse(disciplines=disciplines_sorted, teams=[])

    # Sort: if distance present, sort by distance then name; else by name
    if has_geo:
        teams_out.sort(
            key=lambda r: (
                r.distance_km or 999999.0,
                r.handler_full_name.lower(),
                r.dog_name.lower(),
            )
        )
    else:
        teams_out.sort(key=lambda r: (r.handler_full_name.lower(), r.dog_name.lower()))

    return PublicMatrixResponse(disciplines=disciplines_sorted, teams=teams_out)


@router.get("/standards", response_model=List[PublicStandardOut])
def public_standards(db: Session = Depends(get_db)):
    """
    Public standards listing.
    Adjust field mapping based on your Standard model fields.
    """
    rows = db.query(Standard).order_by(Standard.standard_id.asc()).all()

    out: List[PublicStandardOut] = []
    for s in rows:
        out.append(
            PublicStandardOut(
                standard_id=s.standard_id,
                name=getattr(s, "name", f"Standard {s.standard_id}"),
                description=getattr(s, "description", None),
                replacement_date=str(getattr(s, "replacement_date", None))
                if getattr(s, "replacement_date", None)
                else None,
            )
        )
    return out


@router.get("/standards/{standard_id}", response_model=PublicStandardOut)
def public_standard(standard_id: int, db: Session = Depends(get_db)):
    s = db.query(Standard).filter(Standard.standard_id == standard_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Standard not found")

    return PublicStandardOut(
        standard_id=s.standard_id,
        name=getattr(s, "name", f"Standard {s.standard_id}"),
        description=getattr(s, "description", None),
        replacement_date=str(getattr(s, "replacement_date", None))
        if getattr(s, "replacement_date", None)
        else None,
    )

@router.post("/track")
def track_public_portal_event(
    payload: PublicPortalTrackIn,
    request: Request,
    db: Session = Depends(get_db),
):
    section = (payload.section or "").strip().lower()
    session_id = (payload.session_id or "").strip() or None

    log_public_event(
        db=db,
        request=request,
        section=section,
        session_id=session_id,
    )
    return {"ok": True}
