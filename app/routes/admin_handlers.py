from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, and_
from decimal import Decimal

from app.database import get_db
from app.schemas.handler_schema import HandlerDuesOut, HandlerDuesUpsertIn, HandlerDuesRosterRow
from app.utils.auth import get_current_user, require_supervisor, require_mfa_verified, user_has_role, require_admin

from app.models.handler import Handler, HandlerDues, Affiliation
from app.models.user import User
from app.models.handler_affiliations import HandlerAffiliation
from app.utils.affiliation_scope import get_affiliation_scope
from app.models.appsettings import AppSetting
from app.schemas.appsettings_schema import DuesSettingsOut, DuesSettingsUpdateIn


from app.schemas.admin_handler_schema import AdminHandlerOut, AdminHandlerListOut, AdminHandlerPatch

router = APIRouter(prefix="/admin/handlers", tags=["admin-handlers"])

VALID_HANDLER_STATUSES = {"active", "suspended", "inactive"}


def _handler_to_out(h: Handler) -> AdminHandlerOut:
    u = h.user
    return AdminHandlerOut(
        handler_id=h.handler_id,
        user_id=h.user_id,
        experience_level=h.experience_level,
        status=h.status,
        group_affiliation=h.group_affiliation,
        notes=h.notes,
        created_at=h.created_at,
        updated_at=h.updated_at,
        username=getattr(u, "username", None),
        email=getattr(u, "email", None),
        first_name=getattr(u, "first_name", None),
        last_name=getattr(u, "last_name", None),
    )

from decimal import Decimal, InvalidOperation

def get_handler_dues_default_amount(db: Session) -> Decimal:
    row = (
        db.query(AppSetting)
        .filter(AppSetting.setting_key == "annual_handler_dues_amount")
        .first()
    )

    if not row or not row.setting_value:
        return Decimal("20.00")

    try:
        return Decimal(str(row.setting_value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("20.00")

@router.get("", response_model=AdminHandlerListOut)
def admin_list_handlers(
    q: Optional[str] = Query(default=None, description="Search handler/user fields"),
    status: Optional[str] = Query(default=None, description="active|suspended|inactive"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(require_supervisor),

):

    base = db.query(Handler).join(Handler.user).options(joinedload(Handler.user))

    if status:
        base = base.filter(Handler.status == status)

    if q and q.strip():
        like = f"%{q.strip()}%"
        base = base.filter(
            or_(
                User.first_name.ilike(like),
                User.last_name.ilike(like),
                User.email.ilike(like),
                User.username.ilike(like),
                Handler.experience_level.ilike(like),
                Handler.status.ilike(like),
            )
        )

    total = base.count()
    handlers = base.order_by(Handler.handler_id.desc()).offset(skip).limit(limit).all()
    return AdminHandlerListOut(items=[_handler_to_out(h) for h in handlers], total=total)


@router.get("/{handler_id}", response_model=AdminHandlerOut)
def admin_get_handler(
    handler_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_supervisor),
):

    h = (
        db.query(Handler)
        .options(joinedload(Handler.user))
        .filter(Handler.handler_id == handler_id)
        .first()
    )
    if not h:
        raise HTTPException(status_code=404, detail="Handler not found")
    return _handler_to_out(h)


@router.patch("/{handler_id}", response_model=AdminHandlerOut)
def admin_patch_handler(
    handler_id: int,
    payload: AdminHandlerPatch,
    db: Session = Depends(get_db),
    current_user=Depends(require_supervisor),
    _mfa=Depends(require_mfa_verified),  # <-- add this
):


    h = (
        db.query(Handler)
        .options(joinedload(Handler.user))
        .filter(Handler.handler_id == handler_id)
        .first()
    )
    if not h:
        raise HTTPException(status_code=404, detail="Handler not found")

    if payload.status is not None:
        val = payload.status.strip().lower()
        if val not in VALID_HANDLER_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid handler status")
        h.status = val

    if payload.experience_level is not None:
        h.experience_level = payload.experience_level

    if payload.notes is not None:
        h.notes = payload.notes

    db.add(h)
    db.commit()
    db.refresh(h)
    return _handler_to_out(h)

@router.post("/{handler_id}/dues", response_model=HandlerDuesOut)
def upsert_handler_dues(
    handler_id: int,
    payload: HandlerDuesUpsertIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):

    default_amount = float(get_handler_dues_default_amount(db))

    dues = (
        db.query(HandlerDues)
        .filter(
            HandlerDues.handler_id == handler_id,
            HandlerDues.dues_year == payload.dues_year,
        )
        .first()
    )

    if not dues:
        dues = HandlerDues(
            handler_id=handler_id,
            dues_year=payload.dues_year,
            amount_due=get_handler_dues_default_amount(db),
        )
        db.add(dues)

    dues.status = payload.status

    if payload.status == "paid":
        dues.amount_paid = payload.amount_paid if payload.amount_paid is not None else default_amount
        dues.paid_on = payload.paid_on
        dues.payment_method = payload.payment_method
        dues.reference_note = payload.reference_note

    elif payload.status == "waived":
        dues.amount_paid = 0.00
        dues.paid_on = payload.paid_on
        dues.payment_method = payload.payment_method
        dues.reference_note = payload.reference_note

    else:  # unpaid
        dues.amount_paid = 0.00
        dues.paid_on = None
        dues.payment_method = None
        dues.reference_note = payload.reference_note

    dues.recorded_by_user_id = current_user.user_id

    db.commit()
    db.refresh(dues)
    return dues

@router.get("/admin/dues", response_model=list[HandlerDuesOut])
def list_dues(
    year: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    scope = get_affiliation_scope(db, current_user)

    q = (
        db.query(HandlerDues)
        .join(Handler, Handler.handler_id == HandlerDues.handler_id)
    )

    if scope is None:
        # admin
        pass
    elif user_has_role(current_user, "supervisor"):
        if not scope:
            return []

        q = (
            q.join(
                HandlerAffiliation,
                HandlerAffiliation.handler_id == Handler.handler_id,
            )
            .filter(
                HandlerAffiliation.affiliation_id.in_(scope),
                HandlerAffiliation.ended_at.is_(None),
            )
        )
    else:
        # non-admin/supervisor → no access
        return []

    return q.filter(HandlerDues.dues_year == year).all()


@router.get("/dues/me", response_model=HandlerDuesOut | None)
def get_my_dues(
    year: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    handler = (
        db.query(Handler)
        .filter(Handler.user_id == current_user.user_id)
        .first()
    )

    if not handler:
        return None

    dues = (
        db.query(HandlerDues)
        .filter(
            HandlerDues.handler_id == handler.handler_id,
            HandlerDues.dues_year == year,
        )
        .first()
    )

    return dues



@router.get("/dues/roster", response_model=list[HandlerDuesRosterRow])
def dues_roster(
    year: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    is_admin = user_has_role(current_user, "admin")
    is_supervisor = user_has_role(current_user, "supervisor")

    if not (is_admin or is_supervisor):
        raise HTTPException(status_code=403, detail="Not authorized")

    scope = get_affiliation_scope(db, current_user)

    default_amount = float(get_handler_dues_default_amount(db))

    q = (
        db.query(
            Handler.handler_id.label("handler_id"),
            User.first_name.label("first_name"),
            User.last_name.label("last_name"),
            User.email.label("email"),
            HandlerDues.status.label("status"),
            HandlerDues.amount_due.label("amount_due"),
            HandlerDues.amount_paid.label("amount_paid"),
            HandlerDues.paid_on.label("paid_on"),
            HandlerDues.payment_method.label("payment_method"),
            HandlerDues.reference_note.label("reference_note"),
        )
        .join(User, User.user_id == Handler.user_id)
        .filter(User.is_active.is_(True))
        .outerjoin(
            HandlerDues,
            and_(
                HandlerDues.handler_id == Handler.handler_id,
                HandlerDues.dues_year == year,
            ),
        )
    )

    if is_supervisor and not is_admin:
        if not scope:
            return []

        q = (
            q.join(
                HandlerAffiliation,
                and_(
                    HandlerAffiliation.handler_id == Handler.handler_id,
                    HandlerAffiliation.ended_at.is_(None),
                ),
            )
            .filter(HandlerAffiliation.affiliation_id.in_(scope))
        )

    q = q.filter(Handler.status != "inactive")

    rows = (
        q.distinct()
        .order_by(User.last_name.asc(), User.first_name.asc())
        .all()
    )

    return [
        HandlerDuesRosterRow(
            handler_id=row.handler_id,
            handler_name=f"{row.first_name} {row.last_name}".strip(),
            email=row.email,
            dues_year=year,
            status=row.status or "unpaid",
            amount_due=float(row.amount_due) if row.amount_due is not None else default_amount,
            amount_paid=float(row.amount_paid) if row.amount_paid is not None else None,
            paid_on=row.paid_on,
            payment_method=row.payment_method,
            reference_note=row.reference_note,
        )
        for row in rows
    ]



@router.get("/settings/dues", response_model=DuesSettingsOut)
def get_dues_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):

    amount = get_handler_dues_default_amount(db)
    return DuesSettingsOut(annual_handler_dues_amount=float(amount))


@router.put("/settings/update-dues", response_model=DuesSettingsOut)
def update_dues_settings(
    payload: DuesSettingsUpdateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):

    row = (
        db.query(AppSetting)
        .filter(AppSetting.setting_key == "annual_handler_dues_amount")
        .first()
    )

    value_str = f"{Decimal(str(payload.annual_handler_dues_amount)):.2f}"

    if not row:
        row = AppSetting(
            setting_key="annual_handler_dues_amount",
            setting_value=value_str,
        )
        db.add(row)
    else:
        row.setting_value = value_str

    db.commit()

    return DuesSettingsOut(
        annual_handler_dues_amount=float(Decimal(value_str))
    )
