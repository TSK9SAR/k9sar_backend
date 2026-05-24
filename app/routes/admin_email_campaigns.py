# app/routes/admin_email_campaigns.py

from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, text
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy import exists
from sqlalchemy.orm import aliased
from sqlalchemy import select

from app.database import get_db
from app.models.discipline_group import DisciplineGroup
from app.models.user import User
from app.models.role import Role
from app.models.user_roles import user_roles
from app.models.handler import Affiliation, Handler
from app.models.handler_affiliations import HandlerAffiliation
from app.models.team import Team
from app.models.certification import Certification
from app.models.standard import Standard
from app.models.discipline import Discipline
from app.services.mailer import send_email
from app.models.email_campaigns import EmailCampaign, EmailCampaignRecipient
from app.models.dog import Dog
from app.utils.auth import require_supervisor
from app.models.user_discipline_group import user_discipline_groups
from markdown import markdown
import bleach


from app.schemas.email_campaigns import (
    EmailAudiencePreviewRequest,
    EmailAudiencePreviewOut,
    EmailAudienceRecipientOut,
    EmailAudienceSendRequest,
    EmailAudienceSendOut,
)

from app.utils.auth import get_current_user, require_mfa_verified, require_supervisor
from app.utils.affiliation_scope import get_affiliation_scope
from pydantic import BaseModel


router = APIRouter(
    prefix="/admin/email-audience",
    tags=["Admin Email Audience"],
)

def _full_name_from_id(db: Session, user_id: int | None) -> str:
    if not user_id:
        return "Unknown"

    user = (
        db.query(User)
        .filter(User.user_id == user_id)
        .first()
    )

    if not user:
        return f"User {user_id}"

    return _full_name(user)


def _full_name(user: User) -> str:
    name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return name or user.email or f"User {user.user_id}"



def _user_has_role(db: Session, user_id: int, role_name: str) -> bool:
    return (
        db.query(Role)
        .join(user_roles, user_roles.c.role_id == Role.role_id)
        .filter(user_roles.c.user_id == user_id)
        .filter(Role.role_name == role_name)
        .first()
        is not None
    )

# def _user_is_admin(user: User) -> bool:
#     return any(
#         (getattr(role, "role_name", "") or "").lower() == "admin"
#         for role in getattr(user, "roles", [])
#     )


# def _user_is_evaluator(user: User) -> bool:
#     return any(
#         (getattr(role, "role_name", "") or "").lower() == "evaluator"
#         for role in getattr(user, "roles", [])
#     )

ALLOWED_TAGS = [
    "p", "br", "strong", "em",
    "ul", "ol", "li",
    "blockquote",
    "code", "pre",
    "a",
    "h1", "h2", "h3",
]

ALLOWED_ATTRS = {
    "a": ["href", "title", "target", "rel"],
}


def render_markdown_email(md_text: str) -> str:
    raw_html = markdown(
        md_text or "",
        extensions=[
            "extra",
            "nl2br",
            "sane_lists",
        ],
        output_format="html5",
    )

    return bleach.clean(
        raw_html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        strip=True,
    )

def _build_email_audience(
    db: Session,
    current_user: User,
    req: EmailAudiencePreviewRequest,
):
    filters = req.filters
    excluded_ids = set(req.excluded_user_ids or [])
    today = date.today()

    q = db.query(User).filter(User.is_active == True)  # noqa: E712

    needs_handler = any([
        filters.user_type in ("handlers", None, ""),
        filters.affiliation_id,
        filters.active_handlers_only,
        filters.discipline_group_id is not None,
        filters.discipline_id is not None,
        filters.certification_status,
        filters.expiring_within_days is not None,
        filters.special_rule == "handlers_no_active_certifications",
        filters.q and filters.q.strip(),
    ])

    if filters.user_type in ("users", "evaluators", "supervisors", "administrators"):
        needs_handler = False

    if filters.special_rule == "handlers_no_active_certifications":
        needs_handler = True

    if needs_handler:
        q = q.join(Handler, Handler.user_id == User.user_id)
        q = q.outerjoin(
            HandlerAffiliation,
            HandlerAffiliation.handler_id == Handler.handler_id,
        )

    if filters.special_rule == "evaluators_missing_signature":
        q = q.join(
            user_discipline_groups,
            user_discipline_groups.c.user_id == User.user_id,
        )
        q = q.filter(
            or_(
                User.signature_url.is_(None),
                User.signature_url == "",
            )
        )

    elif filters.special_rule == "handlers_no_active_certifications":
        current_cert_exists = (
            db.query(Certification.certification_id)
            .join(Team, Team.team_id == Certification.team_id)
            .filter(Team.handler_id == Handler.handler_id)
            .filter(Certification.expires_at.isnot(None))
            .filter(Certification.expires_at >= today)
            .exists()
        )
        q = q.filter(~current_cert_exists)

    if filters.user_type == "evaluators":
        q = q.join(
            user_discipline_groups,
            user_discipline_groups.c.user_id == User.user_id,
        )

    elif filters.user_type == "supervisors":
        q = (
            q.join(user_roles, user_roles.c.user_id == User.user_id)
            .join(Role, Role.role_id == user_roles.c.role_id)
            .filter(Role.role_name == "supervisor")
        )

    elif filters.user_type == "administrators":
        q = (
            q.join(user_roles, user_roles.c.user_id == User.user_id)
            .join(Role, Role.role_id == user_roles.c.role_id)
            .filter(Role.role_name == "admin")
        )

    q = q.filter(User.email.isnot(None))
    q = q.filter(User.email != "")

    if excluded_ids:
        q = q.filter(~User.user_id.in_(excluded_ids))

    if filters.user_ids:
        q = q.filter(User.user_id.in_(filters.user_ids))

    if needs_handler and filters.affiliation_id:
        q = q.filter(HandlerAffiliation.affiliation_id == filters.affiliation_id)

    if needs_handler and filters.active_handlers_only:
        q = q.filter(
            or_(
                HandlerAffiliation.ended_at.is_(None),
                HandlerAffiliation.ended_at > today,
            )
        )

    if filters.q and filters.q.strip():
        search = f"%{filters.q.strip()}%"

        base_search = or_(
            User.first_name.ilike(search),
            User.last_name.ilike(search),
            User.email.ilike(search),
        )

        if needs_handler:
            dog_match = (
                db.query(Team.team_id)
                .join(Dog, Dog.dog_id == Team.dog_id)
                .filter(Team.handler_id == Handler.handler_id)
                .filter(Dog.name.ilike(search))
                .exists()
            )
            q = q.filter(or_(base_search, dog_match))
        else:
            q = q.filter(base_search)

    needs_cert_filter = any([
        filters.discipline_group_id is not None,
        filters.discipline_id is not None,
        filters.certification_status,
        filters.expiring_within_days is not None,
    ])

    if needs_cert_filter:
        cert_q = (
            db.query(Certification.certification_id)
            .join(Team, Team.team_id == Certification.team_id)
            .join(Standard, Standard.standard_id == Certification.standard_id)
            .join(Discipline, Discipline.discipline_id == Standard.discipline_id)
            .filter(Team.handler_id == Handler.handler_id)
        )

        if filters.discipline_group_id:
            cert_q = cert_q.filter(Discipline.group_id == filters.discipline_group_id)

        if filters.discipline_id:
            cert_q = cert_q.filter(Standard.discipline_id == filters.discipline_id)

        if filters.certification_status:
            status = filters.certification_status

            if status == "active":
                cert_q = cert_q.filter(Certification.status == "active")
                cert_q = cert_q.filter(
                    or_(
                        Certification.expires_at.is_(None),
                        Certification.expires_at >= today,
                    )
                )
            elif status == "expired":
                cert_q = cert_q.filter(Certification.status == "active")
                cert_q = cert_q.filter(Certification.expires_at.isnot(None))
                cert_q = cert_q.filter(Certification.expires_at < today)
            else:
                cert_q = cert_q.filter(Certification.status == status)

        if filters.expiring_within_days is not None:
            cutoff = today + timedelta(days=filters.expiring_within_days)
            cert_q = cert_q.filter(Certification.status == "active")
            cert_q = cert_q.filter(Certification.expires_at.isnot(None))
            cert_q = cert_q.filter(Certification.expires_at >= today)
            cert_q = cert_q.filter(Certification.expires_at <= cutoff)

        q = q.filter(cert_q.exists())

    return (
        q.distinct(User.user_id)
        .order_by(User.last_name, User.first_name)
        .limit(500)
        .all()
    )


@router.post("/preview", response_model=EmailAudiencePreviewOut)
def preview_email_audience(
    req: EmailAudiencePreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
    # mfa_ok: bool = Depends(require_mfa_verified),
):

    users = _build_email_audience(db, current_user, req)

    recipients = []

    for user in users:
        affiliation_name = None

        if getattr(user, "handler", None):
            active_aff = (
                db.query(HandlerAffiliation)
                .filter(HandlerAffiliation.handler_id == user.handler.handler_id)
                .filter(HandlerAffiliation.ended_at.is_(None))
                .first()
            )

            if active_aff:
                affiliation_name = str(active_aff.affiliation_id)

        recipients.append(
            EmailAudienceRecipientOut(
                user_id=user.user_id,
                name=_full_name(user),
                email=user.email,
                affiliation=affiliation_name,
                is_evaluator=_user_has_role(db, user.user_id, "evaluator"),
            )
        )

    return EmailAudiencePreviewOut(
        total=len(recipients),
        recipients=recipients,
    )

@router.post("/send", response_model=EmailAudienceSendOut)
def send_email_audience(
    req: EmailAudienceSendRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
    # mfa_ok: bool = Depends(require_mfa_verified),
):

    subject = (req.subject or "").strip()
    body_text = (req.body_text or "").strip()
    reply_to = current_user.email if req.enable_reply else None

    sender_name = f"{current_user.first_name or ''} {current_user.last_name or ''}".strip()
    sender_email = current_user.email or ""

    footer = "\n\n—\n"
    footer += f"Sent by {sender_name} via TSK9SAR Member Communication\n"

    if req.enable_reply:
        footer += f"Reply directly to this email to respond to {sender_name} ({sender_email}).\n"
    else:
        footer += "This mailbox is not monitored for replies.\n"

    body_text = body_text + footer

    if not subject:
        raise HTTPException(status_code=400, detail="Subject is required.")

    if not body_text:
        raise HTTPException(status_code=400, detail="Message body is required.")

    preview_req = EmailAudiencePreviewRequest(
        filters=req.filters,
        excluded_user_ids=req.excluded_user_ids,
    )

    users = _build_email_audience(db, current_user, preview_req)

    if not users:
        raise HTTPException(status_code=400, detail="No recipients matched these filters.")

    campaign = EmailCampaign(
        sent_by_user_id=current_user.user_id,
        subject=subject,
        body_text=body_text,
        filter_json=req.filters.model_dump(),
        recipient_count=len(users),
        status="sending",
    )

    db.add(campaign)
    db.flush()

    recipient_rows = []

    for user in users:
        row = EmailCampaignRecipient(
            campaign_id=campaign.campaign_id,
            user_id=user.user_id,
            email=user.email,
            display_name=_full_name(user),
            status="pending",
        )
        db.add(row)
        recipient_rows.append((row, user))

    db.commit()

    sent_count = 0
    failed_count = 0

    for row, user in recipient_rows:
        try:
            personalized_body = body_text.replace(
                "{first_name}",
                user.first_name or "",
            )

            personalized_body = personalized_body.replace(
                "{last_name}",
                user.last_name or "",
            )

            personalized_body = personalized_body.replace(
                "{name}",
                _full_name(user),
            )

            html_body = render_markdown_email(personalized_body)

            send_email(
                to_email=row.email,
                reply_to=reply_to,
                subject=subject,
                text_body=personalized_body,
                html_body=html_body,
            )

            row.status = "sent"
            row.sent_at = datetime.utcnow()
            sent_count += 1

        except Exception as exc:
            row.status = "failed"
            row.error_text = str(exc)[:1000]
            failed_count += 1

        db.add(row)
        db.commit()

    campaign.sent_at = datetime.utcnow()

    if failed_count == 0:
        campaign.status = "sent"
    elif sent_count > 0:
        campaign.status = "partial_failed"
    else:
        campaign.status = "failed"

    campaign.recipient_count = len(users)

    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    return EmailAudienceSendOut(
        campaign_id=campaign.campaign_id,
        recipient_count=len(users),
        sent_count=sent_count,
        failed_count=failed_count,
        status=campaign.status,
    )

@router.get("/activity/email-campaigns")
def email_campaign_activity(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):

    rows = (
        db.query(EmailCampaign)
        .order_by(
            EmailCampaign.sent_at.is_(None),
            EmailCampaign.sent_at.desc(),
            EmailCampaign.created_at.desc(),
        )
        .limit(200)
        .all()
    )

    return [
        {
            "campaign_id": c.campaign_id,
            "created_at": c.created_at,
            "sent_at": c.sent_at,
            "sent_by_user_id": c.sent_by_user_id,
            "sent_by_name": _full_name_from_id(db, c.sent_by_user_id) if getattr(c, "sent_by_user_id", None) else None,
            "subject": c.subject,
            "body_text": c.body_text,
            "recipient_count": c.recipient_count,
            "status": c.status,
            "filter_json": c.filter_json,
        }
        for c in rows
    ]


class AudienceInterpretIn(BaseModel):
    query: str

@router.post("/interpret")
def interpret_email_audience(
    payload: AudienceInterpretIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor),
):

    text = (payload.query or "").strip().lower()

    filters = {
        "q": None,
        "user_ids": [],
        "discipline_group_id": None,
        "discipline_id": None,
        "certification_status": None,
        "affiliation_id": None,
        "expiring_within_days": None,
        "active_handlers_only": True,
        "special_rule": None,
        "user_type": None,
    }

    notes = []

    if (
        "handler" in text
        and (
            "no active certification" in text
            or "no active certifications" in text
            or "without active certification" in text
            or "without active certifications" in text
        )
    ):
        filters["special_rule"] = "handlers_no_active_certifications"
        filters["user_type"] = "handlers"
        notes.append("handlers with no active certifications")
        print("MATCH: handlers_no_active_certifications")

    elif (
        "evaluator" in text
        and (
            "no signature" in text
            or "missing signature" in text
            or "without signature" in text
        )
    ):
        filters["special_rule"] = "evaluators_missing_signature"
        notes.append("evaluators wmissing signature")
        print("MATCH: evaluators_missing_signature")

    elif "expired" in text:
        filters["certification_status"] = "expired"
        notes.append("certification status = expired")

    elif "active" in text or "active certification" in text:
        filters["certification_status"] = "active"
        notes.append("certification status = active")

    elif "pending" in text:
        filters["certification_status"] = "pending"
        notes.append("certification status = pending")

    elif "suspended" in text:
        filters["certification_status"] = "suspended"
        notes.append("certification status = suspended")

    elif "revoked" in text:
        filters["certification_status"] = "revoked"
        notes.append("certification status = revoked")


    if "inactive" in text:
        filters["active_handlers_only"] = False
        notes.append("including inactive handlers")

    elif "active handler" in text or "active handlers" in text:
        filters["active_handlers_only"] = True
        notes.append("active handlers only")


    # Expiring within N days
    import re
    m = re.search(r"expir(?:e|ing|es).*?(\d+)\s*days", text)
    if m:
        filters["expiring_within_days"] = int(m.group(1))
        notes.append(f"expiring within {m.group(1)} days")


    # User IDs
    id_match = re.search(r"user ids?\s*[:=]?\s*([0-9,\s;]+)", text)
    if id_match:
        ids = [
            int(x)
            for x in re.split(r"[\s,;]+", id_match.group(1))
            if x.strip().isdigit()
        ]
        filters["user_ids"] = ids
        notes.append(f"{len(ids)} explicit user id(s)")

    DISCIPLINE_ALIASES = {
    "hrd": "human remains detection",
    "trailing": "trailing",
    "area": "area search",
    "airscent": "air scent",
    "air scent": "air scent",
    }

    # Discipline lookup by name
    disciplines = db.query(Discipline).all()
    for d in disciplines:
        name = (d.name or "").strip().lower()
        if name and name in text:
            filters["discipline_id"] = d.discipline_id
            notes.append(f"discipline = {d.name}")
            break

    # Discipline group lookup by name
    groups = db.query(DisciplineGroup).all()
    for g in groups:
        name = (g.name or "").strip().lower()
        if name and name in text:
            filters["discipline_group_id"] = g.group_id
            notes.append(f"discipline group = {g.name}")
            break

    # Affiliation lookup by name
    affiliations = db.query(Affiliation).all()
    for a in affiliations:
        name = (a.name or "").strip().lower()
        if name and name in text:
            filters["affiliation_id"] = a.affiliation_id
            notes.append(f"affiliation = {a.name}")
            break

    print("FINAL FILTERS:", filters)
    print("NOTES:", notes)
    print("=== EMAIL AUDIENCE INTERPRET END ===")

    return {
        "filters": filters,
        "explanation": (
            "Generated filters: " + "; ".join(notes)
            if notes
            else "No specific filters recognized. Please adjust the filters manually."
        ),
    }