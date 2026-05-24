from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, aliased
from sqlalchemy import distinct
from sqlalchemy import func, literal, case
from datetime import datetime, date, timedelta, timezone
from typing import Optional, Union, List
from sqlalchemy import or_, and_

from app.database import get_db
from app.models.handler_affiliations import AffiliationChangeRequest
from app.utils.affiliation_scope import get_affiliation_scope
from app.utils.auth import get_current_user
from app.utils.authz import (
    has_role,
    can_manage_members,
    can_manage_teams,
    can_manage_admin_only,
    has_role_db,
)

from app.models.user import User
from app.models.handler import Handler, HandlerDues, Affiliation
from app.models.dog import Dog
from app.models.team import Team
from app.models.certification import Certification
from app.models.standard import Standard
from app.models.discipline import Discipline
from app.models.handler_affiliations import HandlerAffiliation
from app.models.appsettings import AppSetting

from app.schemas.dashboard_schema import (
    DashboardSummaryOut,
    DashboardPermissions,
    DashboardKpis,
    DashboardQueues,
    DashboardTrends,
    ExpiringCertRow,
    RecentActivityRow,
    TrendPoint,
    RecentCertActivityRow,
    DashboardDues,
    DashboardSettingsOut,
          # must exist in dashboard_schema.py
)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

from datetime import date, timedelta

def expiring_window_filters(window_days: int):
    today = date.today()
    end = today + timedelta(days=int(window_days))
    return (today, end)

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

def scoped_team_ids_query(db: Session, current_user: User):
    q = (
        db.query(Team.team_id)
        .join(Handler, Handler.handler_id == Team.handler_id)
        .join(User, User.user_id == Handler.user_id)
        .filter(func.coalesce(Team.status, "active") != "inactive")
        .filter(User.is_active.is_(True))
    )

    scope = get_affiliation_scope(db, current_user)

    if scope is None:
        # admin: unrestricted
        return q.distinct()

    if has_role(current_user, "supervisor"):
        if not scope:
            return q.filter(literal(False)).distinct()

        return (
            q.join(
                HandlerAffiliation,
                HandlerAffiliation.handler_id == Handler.handler_id,
            )
            .filter(
                HandlerAffiliation.affiliation_id.in_(scope),
                HandlerAffiliation.ended_at.is_(None),
            )
            .distinct()
        )

    handler = (
        db.query(Handler)
        .filter(Handler.user_id == current_user.user_id)
        .first()
    )
    handler_id = handler.handler_id if handler else -1

    return q.filter(Team.handler_id == handler_id).distinct()

def get_bool_setting(db: Session, key: str, default: bool = False) -> bool:
    row = (
        db.query(AppSetting)
        .filter(AppSetting.setting_key == key)
        .first()
    )
    if not row or row.setting_value is None:
        return default

    value = str(row.setting_value).strip().lower()
    return value in {"1", "true", "yes", "on"}

def normalize_when(val, fallback_now: datetime) -> datetime:
    """Normalize a date/datetime/str into a timezone-aware datetime."""
    if val is None:
        return fallback_now

    # guard for MySQL "zero date" strings
    try:
        if isinstance(val, str) and val.startswith("0000-00-00"):
            return fallback_now
    except Exception:
        pass

    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)

    if isinstance(val, date):
        return datetime(val.year, val.month, val.day, tzinfo=timezone.utc)

    if isinstance(val, str):
        try:
            s = val.strip().replace(" ", "T")
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return fallback_now

    return fallback_now


def as_date(val) -> Optional[date]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    return None

now = _utcnow()

def full_name(first: Optional[str], last: Optional[str]) -> str:
    nm = f"{(first or '').strip()} {(last or '').strip()}".strip()
    return nm or "—"


@router.get("/summary", response_model=DashboardSummaryOut)
def dashboard_summary(
    window_days: int = 90,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    team_ids_sq = scoped_team_ids_query(db, current_user).subquery()

    # Use DATE cutoffs because Certification.expires_at is a Date column
    today_d = date.today()
    d30 = today_d + timedelta(days=30)
    d90 = today_d + timedelta(days=90)
    window_start = today_d - timedelta(days=window_days)

    # Base team query (exclude inactive teams)
    team_q = (
        db.query(Team)
        .join(team_ids_sq, Team.team_id == team_ids_sq.c.team_id)
    )

    teams_count = team_q.count()

    handlers_count = (
        db.query(func.count(func.distinct(Handler.handler_id)))
        .select_from(Team)
        .join(team_ids_sq, Team.team_id == team_ids_sq.c.team_id)
        .join(Handler, Handler.handler_id == Team.handler_id)
        .join(User, User.user_id == Handler.user_id)
        .filter(User.is_active.is_(True))
        .scalar()
    ) or 0

    # handlers_count = (
    # db.query(func.count(Handler.handler_id))
    #     .join(User, User.user_id == Handler.user_id)
    #     .filter(User.is_active.is_(True))
    #     .scalar()
    # ) or 0

    # dogs count within scope (distinct dog_id from teams)
    dogs_count = team_q.with_entities(func.count(func.distinct(Team.dog_id))).scalar() or 0

    # certs expiring
    today, end = expiring_window_filters(window_days)

    latest_active_cert_sq = (
        db.query(
            Certification.team_id.label("team_id"),
            Certification.standard_id.label("standard_id"),
            func.max(Certification.certification_id).label("latest_certification_id"),
        )
        .group_by(Certification.team_id, Certification.standard_id)
        .subquery()
    )
        
    cert_q = (
        db.query(Certification)
        .join(
            latest_active_cert_sq,
            Certification.certification_id == latest_active_cert_sq.c.latest_certification_id,
        )
        .join(Team, Team.team_id == Certification.team_id)
        .join(team_ids_sq, Team.team_id == team_ids_sq.c.team_id)
        .filter(Certification.expires_at.isnot(None))
    )


    today_30, end_30 = expiring_window_filters(30)
    today_90, end_90 = expiring_window_filters(90)

    certs_exp_30 = cert_q.filter(
        Certification.expires_at >= today_30,
        Certification.expires_at <= end_30,
    ).count()

    certs_exp_90 = cert_q.filter(
        Certification.expires_at >= today_90,
        Certification.expires_at <= end_90,
    ).count()

    # expiring queue (soonest first
    expiring_q = (
        db.query(
            Certification.certification_id,
            Certification.team_id,
            Certification.expires_at,
            Discipline.name.label("discipline_name"),
            Dog.name.label("dog_name"),
            User.first_name.label("handler_first"),
            User.last_name.label("handler_last"),
        )
        .join(
            latest_active_cert_sq,
            Certification.certification_id == latest_active_cert_sq.c.latest_certification_id,
        )
        .join(Team, Team.team_id == Certification.team_id)
        .join(team_ids_sq, Team.team_id == team_ids_sq.c.team_id)
        .join(Dog, Dog.dog_id == Team.dog_id)
        .join(Handler, Handler.handler_id == Team.handler_id)
        .join(User, User.user_id == Handler.user_id)
        .join(Standard, Standard.standard_id == Certification.standard_id)
        .join(Discipline, Discipline.discipline_id == Standard.discipline_id)
        .filter(Certification.expires_at.isnot(None))
        .filter(Certification.expires_at >= today)
        .filter(Certification.expires_at <= end)
    )

    expiring_rows = (
        expiring_q
        .order_by(Certification.expires_at.asc())
        .limit(50)
        .all()
    )

    expiring_out: List[ExpiringCertRow] = []
    for r in expiring_rows:
        exp = as_date(r.expires_at)
        days_left = (exp - today_d).days if exp is not None else None

        expiring_out.append(
            ExpiringCertRow(
                certification_id=r.certification_id,
                team_id=r.team_id,
                handler_name=full_name(r.handler_first, r.handler_last),
                dog_name=r.dog_name,
                standard_name=r.discipline_name,
                expires_at=r.expires_at,
                days_left=days_left,
            )
        )
    
    # -------------------------------------------------------------------------
    # Recent activity (legacy stub)
    # -------------------------------------------------------------------------
    recent_activity_q = (
        db.query(
            literal("certification").label("type"),
            Certification.created_at.label("when"),
            func.concat("Certification #", Certification.certification_id).label("summary"),
        )
        .join(Team, Team.team_id == Certification.team_id)
        .join(team_ids_sq, Team.team_id == team_ids_sq.c.team_id)
        .order_by(Certification.certification_id.desc())
    )
    recent_activity_rows = (
        recent_activity_q
        .order_by(Certification.certification_id.desc())
        .limit(20)
        .all()
    )

    recent_out: List[RecentActivityRow] = [
        RecentActivityRow(
            type=r.type,
            when=normalize_when(r.when, now),
            summary=r.summary,
        )
        for r in recent_activity_rows
    ]

    # -------------------------------------------------------------------------
    # Recent certification activity feed (what your UI wants)
    # Handler, Dog, Discipline, Action (issued/revoked), Actor, When
    # -------------------------------------------------------------------------

    Actor = aliased(User)
    Issuer = aliased(User)

    recent_cert_q = (
        db.query(
            Certification.team_id.label("team_id"),
            Dog.name.label("dog_name"),
            Discipline.name.label("discipline"),
            Certification.status.label("cert_status"),
            Certification.created_at.label("created_at"),
            Certification.updated_at.label("updated_at"),
            User.first_name.label("handler_first"),
            User.last_name.label("handler_last"),
            Issuer.first_name.label("issuer_first"),
            Issuer.last_name.label("issuer_last"),
            Issuer.username.label("issuer_username"),
            Actor.first_name.label("actor_first"),
            Actor.last_name.label("actor_last"),
            Actor.username.label("actor_username"),
        )
        .join(Team, Team.team_id == Certification.team_id)
        .join(team_ids_sq, Team.team_id == team_ids_sq.c.team_id)
        .join(Dog, Dog.dog_id == Team.dog_id)
        .join(Handler, Handler.handler_id == Team.handler_id)
        .join(User, User.user_id == Handler.user_id)
        .join(Standard, Standard.standard_id == Certification.standard_id)
        .join(Discipline, Discipline.discipline_id == Standard.discipline_id)
        .outerjoin(Actor, Actor.user_id == Certification.last_actor_user_id)
        .outerjoin(Issuer, Issuer.user_id == Certification.supervisor_id)
        .filter(func.coalesce(Certification.updated_at, Certification.created_at).isnot(None))
        .filter(func.coalesce(Certification.updated_at, Certification.created_at) >= window_start)
    )

    rows = (
        recent_cert_q
        .order_by(func.coalesce(Certification.updated_at, Certification.created_at).desc())
        .limit(50)
        .all()
    )

    recent_cert_out: List[RecentCertActivityRow] = []

    for r in rows:
        # Action: if cert is revoked -> revoked else issued
        # status = (r.cert_status or "").strip().lower()
        # action = "revoked" if status == "revoked" else "issued"
        action = (r.cert_status or "").strip().lower()   
        # When: revoked uses updated_at if present; otherwise created_at
        when_raw = r.updated_at if action == "revoked" else r.created_at
        if when_raw is None:
            when_raw = r.updated_at or r.created_at

        when = normalize_when(when_raw, now)

        # Discipline must be a string (avoid bool/None surprises)
        disc_raw = getattr(r, "discipline", None)
        if isinstance(disc_raw, bool) or disc_raw is None:
            discipline = "—"
        else:
            discipline = str(disc_raw).strip() or "—"

        actor_name = full_name(r.actor_first, r.actor_last)
        if actor_name == "—":
            actor_name = (r.actor_username or "Unknown").strip() or "Unknown"

        issuer_name = full_name(r.issuer_first, r.issuer_last)
        if issuer_name == "—":
            issuer_name = (r.issuer_username or "Unknown").strip() or "Unknown"

        recent_cert_out.append(
            RecentCertActivityRow(
                team_id=r.team_id,
                handler_name=full_name(r.handler_first, r.handler_last),
                dog_name=r.dog_name or "—",
                discipline=discipline,
                issuer_name=issuer_name,
                action=action,
                actor_name=actor_name,
                when=when,
            )
        )

    # -------------------------------------------------------------------------
    # trends stub (kept minimal)
    # -------------------------------------------------------------------------
    trends = DashboardTrends(issued_by_week=[])

    permissions = DashboardPermissions(
        can_manage_members=can_manage_members(current_user),
        can_manage_teams=can_manage_teams(current_user),
        can_manage_disciplines=can_manage_admin_only(current_user),
        can_manage_standards=can_manage_admin_only(current_user),
        can_hard_delete=can_manage_admin_only(current_user),
    )

    #-------------------------------------------------------------------------
    # pending affiliation requests count (supervisor/admin only)
    #--------------------------------------
    scope = get_affiliation_scope(db, current_user)

    pending_aff_q = (
        db.query(func.count(AffiliationChangeRequest.request_id))
        .filter(AffiliationChangeRequest.status == "pending")
    )

    if scope is None:
        pending_affiliations = pending_aff_q.scalar() or 0
    elif has_role(current_user, "supervisor"):
        if not scope:
            pending_affiliations = 0
        else:
            pending_affiliations = (
                pending_aff_q
                .filter(AffiliationChangeRequest.affiliation_id.in_(scope))
                .scalar()
            ) or 0
    else:
        pending_affiliations = 0

    current_year = date.today().year
    is_admin = has_role(current_user, "admin")
    is_supervisor = has_role(current_user, "supervisor")

    my_handler = (
        db.query(Handler)
        .join(User, User.user_id == Handler.user_id)
        .filter(
            Handler.user_id == current_user.user_id,
            User.is_active.is_(True),
        )
        .first()
    )

    my_dues_row = None
    if my_handler:
        my_dues_row = (
            db.query(HandlerDues)
            .filter(
                HandlerDues.handler_id == my_handler.handler_id,
                HandlerDues.dues_year == current_year,
            )
            .first()
        )

    my_dues_status = my_dues_row.status if my_dues_row else "unpaid"

    if not (is_admin or is_supervisor):
        dues = DashboardDues(
            dues_year=current_year,
            status=my_dues_status,
            unpaid_count=0,
            paid_count=0,
            waived_count=0,
            total_count=1 if my_handler else 0,
            is_self_view=True,
        )
    else:
        scope = get_affiliation_scope(db, current_user)

        handlers_q = (
            db.query(Handler.handler_id)
            .join(User, User.user_id == Handler.user_id)
            .filter(User.is_active.is_(True))
        )

        if scope is None:
            # admin: unrestricted
            pass
        else:
            # supervisor
            if not scope:
                dues = DashboardDues(
                    dues_year=current_year,
                    status=my_dues_status,
                    unpaid_count=0,
                    paid_count=0,
                    waived_count=0,
                    total_count=0,
                    is_self_view=False,
                )
            else:
                handlers_q = (
                    handlers_q
                    .join(
                        HandlerAffiliation,
                        and_(
                            HandlerAffiliation.handler_id == Handler.handler_id,
                            HandlerAffiliation.ended_at.is_(None),
                        ),
                    )
                    .filter(HandlerAffiliation.affiliation_id.in_(scope))
                    .distinct()
                )

        if scope is None or scope:
            scoped_handlers_sq = handlers_q.subquery()

            dues_rows = (
                db.query(
                    HandlerDues.status,
                    func.count(func.distinct(scoped_handlers_sq.c.handler_id)).label("cnt"),
                )
                .select_from(scoped_handlers_sq)
                .outerjoin(
                    HandlerDues,
                    and_(
                        HandlerDues.handler_id == scoped_handlers_sq.c.handler_id,
                        HandlerDues.dues_year == current_year,
                    ),
                )
                .group_by(HandlerDues.status)
                .all()
            )

            unpaid_count = 0
            paid_count = 0
            waived_count = 0

            for status, cnt in dues_rows:
                if status == "paid":
                    paid_count = int(cnt or 0)
                elif status == "waived":
                    waived_count = int(cnt or 0)
                else:
                    unpaid_count += int(cnt or 0)

            dues = DashboardDues(
                dues_year=current_year,
                status=my_dues_status,
                unpaid_count=unpaid_count,
                paid_count=paid_count,
                waived_count=waived_count,
                total_count=unpaid_count + paid_count + waived_count,
                is_self_view=False,
            )

    dues_enabled = get_bool_setting(db, "enable_dues_collection", default=False)
    
    return DashboardSummaryOut(
        permissions=permissions,
        kpis=DashboardKpis(
            teams=teams_count,
            handlers=handlers_count,
            dogs=dogs_count,
            pending_affiliation_requests=int(pending_affiliations),
            certs_expiring_30=certs_exp_30,
            certs_expiring_90=certs_exp_90,
        ),
        queues=DashboardQueues(
            expiring_certs=expiring_out,
            recent_activity=recent_out,
            recent_cert_activity=recent_cert_out,
        ),
        trends=trends,
        dues=dues if dues_enabled else None,
        dues_enabled=dues_enabled,
    )

@router.get("/settings", response_model=DashboardSettingsOut)
def dashboard_settings(db: Session = Depends(get_db),):
    dues_enabled = get_bool_setting(db, "enable_dues_collection", default=False)
    return DashboardSettingsOut(
        dues_enabled=dues_enabled,
    )
