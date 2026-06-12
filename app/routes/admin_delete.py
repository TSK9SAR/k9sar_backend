import os, time, json, hmac, hashlib
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, exists, text


from app.database import get_db
from app.utils.auth import get_current_user, require_mfa_verified, get_current_user_no_mfa, require_admin, require_supervisor

from app.models.user import User
from app.models.handler import Handler
from app.models.dog import Dog
from app.models.team import Team
from app.models.certification import Certification, CertificationEvent
from app.models.discipline import Discipline
from app.models.standard import Standard
from app.models.password_reset import PasswordReset
from app.models.user_invite import UserInvite
from app.models.role import Role
from app.models.admin_cleanup_event import AdminCleanupEvent
from app.models.handler_affiliations import HandlerAffiliation
from app.models.forum import ForumTopic, ForumPost, ForumBallotVote, ForumBallot, ForumBallotFeedback, ForumBallotChoice, ForumTopicRead
from app.schemas.forum import CleanupConfirmIn
from app.models.id_headshot import HandlerIdHeadshot, DogIdHeadshot

router = APIRouter(prefix="/admin", tags=["Admin Deletes"])

DELETE_SECRET = os.environ.get("DELETE_CONFIRM_SECRET", "dev-secret-change-me")
TTL_SECONDS = 5 * 60

def log_cleanup_event(
    db: Session,
    *,
    actor_user_id: int,
    action: str,
    entity_type: str,
    entity_id: int | None,
    entity_label: str | None = None,
    deleted_counts: dict | None = None,
    affected_ids: dict | None = None,
    warnings: list[str] | None = None,
    confirmation_text: str | None = None,
):
    db.add(
        AdminCleanupEvent(
            actor_user_id=actor_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_label=entity_label,
            deleted_counts_json=deleted_counts or {},
            affected_ids_json=affected_ids or {},
            warnings_json=warnings or [],
            confirmation_text=confirmation_text,
        )
    )

def dog_headshot_count(db: Session, dog_ids: list[int]) -> int:
    if not dog_ids:
        return 0
    return (
        db.query(DogIdHeadshot)
        .filter(DogIdHeadshot.dog_id.in_(dog_ids))
        .count()
    )

def handler_headshot_count(db: Session, handler_id: int | None) -> int:
    if not handler_id:
        return 0
    return (
        db.query(HandlerIdHeadshot)
        .filter(HandlerIdHeadshot.handler_id == handler_id)
        .count()
    )

def _hmac(payload: dict) -> str:
    msg = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(DELETE_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()

def _now() -> int:
    return int(time.time())

def _require_confirm(body: dict, expected_text: str):
    confirm_text = body.get("confirm_text", "")
    if confirm_text != expected_text:
        raise HTTPException(status_code=422, detail=f'Confirmation text mismatch. Expected "{expected_text}".')

    expires_at = body.get("expires_at")
    confirm_hash = body.get("confirm_hash")
    if not isinstance(expires_at, int) or not confirm_hash:
        raise HTTPException(status_code=422, detail="expires_at and confirm_hash are required")

    if _now() > expires_at:
        raise HTTPException(status_code=409, detail="Delete confirmation expired. Re-run preview.")

    return expires_at, confirm_hash

# ---------- TEAM hard delete (DESTROYS certifications via ORM cascade) ----------
@router.get("/canary")
def supervisor_canary_mfa(
    current_user: User = Depends(require_supervisor),
    _mfa=Depends(require_mfa_verified),
):
    return {"ok": True}

@router.get("/canary_no_mfa")
def supervisor_canary_no_mfa(
    current_user: User = Depends(require_supervisor),
):
    return {"ok": True}

@router.get("/canary_admin")
def admin_canary_mfa(
    current_user: User = Depends(require_admin),
    _mfa=Depends(require_mfa_verified),
):
    return {"ok": True}

@router.get("/canary_admin_no_mfa")
def admin_canary_no_mfa(
    current_user: User = Depends(require_admin),
):
    return {"ok": True}




@router.get("/teams/{team_id}/delete-preview")
def preview_delete_team(
    team_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    _mfa=Depends(require_mfa_verified),
):

    team = db.query(Team).filter(Team.team_id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    cert_ids = [
    r[0]
    for r in db.query(Certification.certification_id)
    .filter(Certification.team_id == team_id)
    .all()
]

    event_count = 0
    if cert_ids:
        event_count = (
            db.query(CertificationEvent)
            .filter(CertificationEvent.certification_id.in_(cert_ids))
            .count()
        )

    # label: handler + dog if available
    label = f"Team {team_id} (handler_id={team.handler_id}, dog_id={team.dog_id})"

    expires_at = _now() + TTL_SECONDS
    hash_payload = {
        "entity": "team",
        "team_id": team_id,
        "cert_count": len(cert_ids),
        "event_count": event_count,
        "expires_at": expires_at,
    }
    return {
        "entity": "team",
        "team_id": team_id,
        "label": label,

        "warnings": ["Hard delete cannot be undone.", "This will permanently remove certifications for this pairing."],
        "expires_at": expires_at,
        "confirm_hash": _hmac(hash_payload),
        "confirm_text_required": f"DELETE TEAM {team_id}",
        "will_delete": {
            "team_row": 1,
            "certifications": len(cert_ids),
            "certification_events": event_count,
        }
    }

@router.post("/teams/{team_id}/hard-delete")
def hard_delete_team(
    team_id: int,
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    _mfa=Depends(require_mfa_verified),
):
    expires_at, confirm_hash = _require_confirm(
        body,
        expected_text=f"DELETE TEAM {team_id}",
    )

    team = db.query(Team).filter(Team.team_id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    cert_ids = [
        r[0]
        for r in db.query(Certification.certification_id)
        .filter(Certification.team_id == team_id)
        .all()
    ]

    event_count = 0
    if cert_ids:
        event_count = (
            db.query(CertificationEvent)
            .filter(CertificationEvent.certification_id.in_(cert_ids))
            .count()
        )

    expected = _hmac({
        "entity": "team",
        "team_id": team_id,
        "cert_count": len(cert_ids),
        "event_count": event_count,
        "expires_at": expires_at,
    })

    if not hmac.compare_digest(expected, confirm_hash):
        raise HTTPException(
            status_code=409,
            detail="Delete confirmation invalid. Re-run preview.",
        )

    try:
        if cert_ids:
            db.query(CertificationEvent).filter(
                CertificationEvent.certification_id.in_(cert_ids)
            ).delete(synchronize_session=False)

            db.query(Certification).filter(
                Certification.certification_id.in_(cert_ids)
            ).delete(synchronize_session=False)

        db.query(Team).filter(
            Team.team_id == team_id
        ).delete(synchronize_session=False)

        log_cleanup_event(
            db,
            actor_user_id=current_user.user_id,
            action="hard_delete_team",
            entity_type="team",
            entity_id=team_id,
            entity_label=f"Team {team_id}",
            deleted_counts={
                "teams": 1,
                "certifications": len(cert_ids),
                "certification_events": event_count,
            },
            affected_ids={
                "team_ids": [team_id],
                "certification_ids": cert_ids,
            },
            warnings=[
                "Team and related certifications were hard-deleted.",
            ],
            confirmation_text=f"DELETE TEAM {team_id}",
        )

        db.commit()
        return {
            "status": "deleted",
            "team_id": team_id,
            "certifications": len(cert_ids),
            "certification_events": event_count,
        }

    except Exception:
        db.rollback()
        raise

def get_orphan_dogs(db: Session):
    return (
        db.query(Dog.dog_id, Dog.name)
        .outerjoin(Team, Team.dog_id == Dog.dog_id)
        .filter(Team.team_id.is_(None))
        .order_by(Dog.dog_id)
        .all()
    )

@router.get("/dogs/orphans/delete-preview")
def preview_delete_orphan_dogs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    _mfa=Depends(require_mfa_verified),
):
    orphan_dogs = get_orphan_dogs(db)

    dog_ids = [int(r[0]) for r in orphan_dogs]
    dog_samples = [
        {"dog_id": int(r[0]), "name": r[1]}
        for r in orphan_dogs[:100]
    ]

    expires_at = _now() + TTL_SECONDS

    hash_payload = {
        "entity": "orphan_dogs",
        "dog_count": len(dog_ids),
        "dog_ids": dog_ids,
        "expires_at": expires_at,
    }

    warnings = [
        "Hard delete cannot be undone.",
        "Only dogs with no teams will be deleted.",
    ]

    if len(dog_ids) > 25:
        warnings.append(
            f"High count: {len(dog_ids)} orphan dogs found. Review the sample list carefully before deleting."
        )

    return {
        "entity": "orphan_dogs",
        "label": "Orphan dogs",
        "will_delete": {
            "dogs": len(dog_ids),
        },
        "sample_ids": {
            "dog_ids": dog_ids[:50],
        },
        "sample_rows": {
            "dogs": dog_samples,
        },
        "warnings": warnings,
        "blocked": False,
        "expires_at": expires_at,
        "confirm_hash": _hmac(hash_payload),
        "confirm_text_required": "DELETE ORPHAN DOGS",
    }

@router.post("/dogs/orphans/hard-delete")
def hard_delete_orphan_dogs(
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    _mfa=Depends(require_mfa_verified),
):
    expires_at, confirm_hash = _require_confirm(
        body,
        expected_text="DELETE ORPHAN DOGS",
    )

    orphan_dogs = get_orphan_dogs(db)
    dog_ids = [int(r[0]) for r in orphan_dogs]

    expected = _hmac({
        "entity": "orphan_dogs",
        "dog_count": len(dog_ids),
        "dog_ids": dog_ids,
        "expires_at": expires_at,
    })

    if not hmac.compare_digest(expected, confirm_hash):
        raise HTTPException(
            status_code=409,
            detail="Delete confirmation invalid. Re-run preview.",
        )

    try:
        if dog_ids:
            db.query(DogIdHeadshot).filter(
                DogIdHeadshot.dog_id.in_(dog_ids)
            ).delete(synchronize_session=False)
            db.query(Dog).filter(
                Dog.dog_id.in_(dog_ids)
            ).delete(synchronize_session=False)

        log_cleanup_event(
            db,
            actor_user_id=current_user.user_id,
            action="hard_delete_orphan_dogs",
            entity_type="orphan_dogs",
            entity_id=None,
            entity_label="Orphan dogs",
            deleted_counts={"dogs": len(dog_ids)},
            affected_ids={"dog_ids": dog_ids},
            warnings=["Only dogs with no teams were deleted."],
            confirmation_text="DELETE ORPHAN DOGS",
        )

        db.commit()

        return {
            "status": "deleted",
            "dogs": len(dog_ids),
            "dog_ids": dog_ids,
        }

    except Exception:
        db.rollback()
        raise

@router.get("/dogs/{dog_id}/delete-preview")
def preview_delete_dog(
    dog_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    _mfa=Depends(require_mfa_verified),
):
    dog = db.query(Dog).filter(Dog.dog_id == dog_id).first()
    if not dog:
        raise HTTPException(status_code=404, detail="Dog not found")

    team_ids = [
        r[0]
        for r in db.query(Team.team_id)
        .filter(Team.dog_id == dog_id)
        .all()
    ]

    cert_ids = []
    if team_ids:
        cert_ids = [
            r[0]
            for r in db.query(Certification.certification_id)
            .filter(Certification.team_id.in_(team_ids))
            .all()
        ]

    event_count = 0
    if cert_ids:
        event_count = (
            db.query(CertificationEvent)
            .filter(CertificationEvent.certification_id.in_(cert_ids))
            .count()
        )

    expires_at = _now() + TTL_SECONDS

    hash_payload = {
        "entity": "dog",
        "dog_id": dog_id,
        "team_count": len(team_ids),
        "cert_count": len(cert_ids),
        "event_count": event_count,
        "expires_at": expires_at,
    }

    label = f"{dog.name} (dog_id={dog_id})"

    return {
        "entity": "dog",
        "dog_id": dog_id,
        "label": label,
        "will_delete": {
            "dog_row": 1,
            "teams": len(team_ids),
            "certifications": len(cert_ids),
            "certification_events": event_count,
        },
        "sample_ids": {
            "team_ids": team_ids[:20],
            "certification_ids": cert_ids[:20],
        },
        "warnings": [
            "Hard delete cannot be undone.",
            "Deleting this dog will also delete every team using this dog.",
            "Certifications and certification audit events for those teams will also be deleted.",
        ],
        "blocked": False,
        "expires_at": expires_at,
        "confirm_hash": _hmac(hash_payload),
        "confirm_text_required": f"DELETE DOG {dog_id}",
    }

@router.post("/dogs/{dog_id}/hard-delete")
def hard_delete_dog(
    dog_id: int,
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    _mfa=Depends(require_mfa_verified),
):
    expires_at, confirm_hash = _require_confirm(
        body,
        expected_text=f"DELETE DOG {dog_id}",
    )

    dog = db.query(Dog).filter(Dog.dog_id == dog_id).first()
    if not dog:
        raise HTTPException(status_code=404, detail="Dog not found")

    team_ids = [
        r[0]
        for r in db.query(Team.team_id)
        .filter(Team.dog_id == dog_id)
        .all()
    ]

    cert_ids = []
    if team_ids:
        cert_ids = [
            r[0]
            for r in db.query(Certification.certification_id)
            .filter(Certification.team_id.in_(team_ids))
            .all()
        ]

    event_count = 0
    if cert_ids:
        event_count = (
            db.query(CertificationEvent)
            .filter(CertificationEvent.certification_id.in_(cert_ids))
            .count()
        )

    expected = _hmac({
        "entity": "dog",
        "dog_id": dog_id,
        "team_count": len(team_ids),
        "cert_count": len(cert_ids),
        "event_count": event_count,
        "expires_at": expires_at,
    })

    if not hmac.compare_digest(expected, confirm_hash):
        raise HTTPException(
            status_code=409,
            detail="Delete confirmation invalid. Re-run preview.",
        )

    try:
        if cert_ids:
            db.query(CertificationEvent).filter(
                CertificationEvent.certification_id.in_(cert_ids)
            ).delete(synchronize_session=False)

            db.query(Certification).filter(
                Certification.certification_id.in_(cert_ids)
            ).delete(synchronize_session=False)

        if team_ids:
            db.query(Team).filter(
                Team.team_id.in_(team_ids)
            ).delete(synchronize_session=False)

        dog_headshots = (
            db.query(DogIdHeadshot)
            .filter(DogIdHeadshot.dog_id == dog_id)
            .count()
        )

        db.query(DogIdHeadshot).filter(
            DogIdHeadshot.dog_id == dog_id
        ).delete(synchronize_session=False)

        db.query(Dog).filter(
            Dog.dog_id == dog_id
        ).delete(synchronize_session=False)

        log_cleanup_event(
            db,
            actor_user_id=current_user.user_id,
            action="hard_delete_dog",
            entity_type="dog",
            entity_id=dog_id,
            entity_label=getattr(dog, "name", None),
            deleted_counts={
                "dogs": 1,
                "teams": len(team_ids),
                "certifications": len(cert_ids),
                "certification_events": event_count,
                "dog_headshots": dog_headshots,
            },
            affected_ids={
                "dog_ids": [dog_id],
                "team_ids": team_ids,
                "certification_ids": cert_ids,
            },
            warnings=[
                "Dog, related teams, certifications, and certification events were hard-deleted.",
            ],
            confirmation_text=f"DELETE DOG {dog_id}",
        )

        db.commit()

        return {
            "status": "deleted",
            "dog_id": dog_id,
            "teams": len(team_ids),
            "certifications": len(cert_ids),
            "certification_events": event_count,
            "dog_headshots": dog_headshots, 
        }

    except Exception:
        db.rollback()
        raise

@router.get("/handlers/{handler_id}/delete-preview")
def preview_delete_handler_keep_user(
    handler_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    _mfa=Depends(require_mfa_verified),
):
    handler = (
        db.query(Handler)
        .filter(Handler.handler_id == handler_id)
        .first()
    )

    if not handler:
        raise HTTPException(status_code=404, detail="Handler not found")

    team_ids = [
        r[0]
        for r in db.query(Team.team_id)
        .filter(Team.handler_id == handler_id)
        .all()
    ]

    dog_ids = [
        r[0]
        for r in db.query(Team.dog_id)
        .filter(Team.handler_id == handler_id)
        .filter(Team.dog_id.isnot(None))
        .all()
    ]

    cert_ids = []
    if team_ids:
        cert_ids = [
            r[0]
            for r in db.query(Certification.certification_id)
            .filter(Certification.team_id.in_(team_ids))
            .all()
        ]

    event_count = 0
    if cert_ids:
        event_count = (
            db.query(CertificationEvent)
            .filter(CertificationEvent.certification_id.in_(cert_ids))
            .count()
        )

    orphan_dog_ids = []

    for dog_id in set(dog_ids):
        other_team_exists = (
            db.query(Team.team_id)
            .filter(Team.dog_id == dog_id)
            .filter(~Team.team_id.in_(team_ids))
            .first()
        )

        if not other_team_exists:
            orphan_dog_ids.append(dog_id)

    affiliation_count = (
        db.query(HandlerAffiliation)
        .filter(HandlerAffiliation.handler_id == handler_id)
        .count()
    )

    expires_at = _now() + TTL_SECONDS

    hash_payload = {
        "entity": "handler_keep_user",
        "mode": "delete_handler_keep_user",
        "handler_id": handler_id,
        "team_count": len(team_ids),
        "dog_count": len(orphan_dog_ids),
        "cert_count": len(cert_ids),
        "event_count": event_count,
        "affiliation_count": affiliation_count,
        "expires_at": expires_at,
    }

    label = f"Handler {handler_id} (user_id={handler.user_id})"

    return {
        "entity": "handler_keep_user",
        "mode": "delete_handler_keep_user",
        "handler_id": handler_id,
        "label": label,

        "will_delete": {
            "handler": 1,
            "handler_affiliations": affiliation_count,
            "teams": len(team_ids),
            "dogs": len(orphan_dog_ids),
            "certifications": len(cert_ids),
            "certification_events": event_count,
        },

        "will_preserve": {
            "user": 1,
        },

        "sample_ids": {
            "team_ids": team_ids[:50],
            "dog_ids": orphan_dog_ids[:50],
            "certification_ids": cert_ids[:50],
        },

        "warnings": [
            "Hard delete cannot be undone.",
            "User account will be preserved.",
            "Only dogs that become orphaned will be deleted.",
        ],

        "blocked": False,
        "expires_at": expires_at,
        "confirm_hash": _hmac(hash_payload),
        "confirm_text_required": f"DELETE HANDLER {handler_id} KEEP USER",
    }

@router.post("/handlers/{handler_id}/hard-delete-keep-user")
def hard_delete_handler_keep_user(
    handler_id: int,
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    _mfa=Depends(require_mfa_verified),
):
    expires_at, confirm_hash = _require_confirm(
        body,
        expected_text=f"DELETE HANDLER {handler_id} KEEP USER",
    )

    handler = (
        db.query(Handler)
        .filter(Handler.handler_id == handler_id)
        .first()
    )

    if not handler:
        raise HTTPException(status_code=404, detail="Handler not found")

    team_ids = [
        r[0]
        for r in db.query(Team.team_id)
        .filter(Team.handler_id == handler_id)
        .all()
    ]

    dog_ids = [
        r[0]
        for r in db.query(Team.dog_id)
        .filter(Team.handler_id == handler_id)
        .filter(Team.dog_id.isnot(None))
        .all()
    ]

    handler_headshots = (
        db.query(HandlerIdHeadshot)
        .filter(HandlerIdHeadshot.handler_id == handler_id)
        .count()
        if handler_id else 0
    )

    cert_ids = []
    if team_ids:
        cert_ids = [
            r[0]
            for r in db.query(Certification.certification_id)
            .filter(Certification.team_id.in_(team_ids))
            .all()
        ]

    event_count = 0
    if cert_ids:
        event_count = (
            db.query(CertificationEvent)
            .filter(CertificationEvent.certification_id.in_(cert_ids))
            .count()
        )

    orphan_dog_ids = []

    for dog_id in set(dog_ids):
        other_team_exists = (
            db.query(Team.team_id)
            .filter(Team.dog_id == dog_id)
            .filter(~Team.team_id.in_(team_ids))
            .first()
        )

        if not other_team_exists:
            orphan_dog_ids.append(dog_id)
    
    dog_headshots = dog_headshot_count(db, orphan_dog_ids)

    affiliation_count = (
        db.query(HandlerAffiliation)
        .filter(HandlerAffiliation.handler_id == handler_id)
        .count()
    )

    expected = _hmac({
        "entity": "handler_keep_user",
        "mode": "delete_handler_keep_user",
        "handler_id": handler_id,
        "team_count": len(team_ids),
        "dog_count": len(orphan_dog_ids),
        "cert_count": len(cert_ids),
        "event_count": event_count,
        "affiliation_count": affiliation_count,
        "expires_at": expires_at,
    })

    if not hmac.compare_digest(expected, confirm_hash):
        raise HTTPException(
            status_code=409,
            detail="Delete confirmation invalid. Re-run preview.",
        )

    try:
        if cert_ids:
            db.query(CertificationEvent).filter(
                CertificationEvent.certification_id.in_(cert_ids)
            ).delete(synchronize_session=False)

            db.query(Certification).filter(
                Certification.certification_id.in_(cert_ids)
            ).delete(synchronize_session=False)

        if team_ids:
            db.query(Team).filter(
                Team.team_id.in_(team_ids)
            ).delete(synchronize_session=False)

        if orphan_dog_ids:
            db.query(DogIdHeadshot).filter(
                DogIdHeadshot.dog_id.in_(orphan_dog_ids)
            ).delete(synchronize_session=False)

            db.query(Dog).filter(
                Dog.dog_id.in_(orphan_dog_ids)
            ).delete(synchronize_session=False)

        db.query(HandlerAffiliation).filter(
            HandlerAffiliation.handler_id == handler_id
        ).delete(synchronize_session=False)

        db.query(HandlerIdHeadshot).filter(
            HandlerIdHeadshot.handler_id == handler_id
        ).delete(synchronize_session=False)

        db.query(Handler).filter(
            Handler.handler_id == handler_id
        ).delete(synchronize_session=False)

        log_cleanup_event(
            db,
            actor_user_id=current_user.user_id,
            action="hard_delete_handler_keep_user",
            entity_type="handler",
            entity_id=handler_id,
            entity_label=f"Handler {handler_id}",
            deleted_counts={
                "handler": 1,
                "handler_affiliations": affiliation_count,
                "teams": len(team_ids),
                "dogs": len(orphan_dog_ids),
                "certifications": len(cert_ids),
                "certification_events": event_count,
                "handler_headshots": handler_headshots,
                "dog_headshots": dog_headshots,
            },
            affected_ids={
                "team_ids": team_ids,
                "dog_ids": orphan_dog_ids,
                "certification_ids": cert_ids,
            },
            warnings=[
                "User account was preserved.",
            ],
            confirmation_text=f"DELETE HANDLER {handler_id} KEEP USER",
        )

        db.commit()

        return {
            "status": "deleted",
            "handler_id": handler_id,
            "teams": len(team_ids),
            "dogs": len(orphan_dog_ids),
            "certifications": len(cert_ids),
            "certification_events": event_count,
            "handler_headshots": handler_headshots,
            "dog_headshots": dog_headshots,
        }

    except Exception:
        db.rollback()
        raise

@router.get("/users/{user_id}/delete-preview")
def preview_delete_user_tree(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    #_mfa=Depends(require_mfa_verified),
):
    cu_id = getattr(current_user, "user_id", None) or getattr(current_user, "id", None)
    if cu_id and int(cu_id) == int(user_id):
        raise HTTPException(status_code=400, detail="Refusing to hard-delete the currently logged-in user.")

    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    handler = db.query(Handler).filter(Handler.user_id == user_id).first()

    handler_id = handler.handler_id if handler else None

    team_ids = []
    dog_ids = []
    cert_ids = []
    orphan_dog_ids = []
    event_count = 0
    affiliation_count = 0

    if handler:
        team_ids = [
            r[0]
            for r in db.query(Team.team_id)
            .filter(Team.handler_id == handler.handler_id)
            .all()
        ]

        dog_ids = [
            r[0]
            for r in db.query(Team.dog_id)
            .filter(Team.handler_id == handler.handler_id)
            .filter(Team.dog_id.isnot(None))
            .all()
        ]

        if team_ids:
            cert_ids = [
                r[0]
                for r in db.query(Certification.certification_id)
                .filter(Certification.team_id.in_(team_ids))
                .all()
            ]

        if cert_ids:
            event_count = (
                db.query(CertificationEvent)
                .filter(CertificationEvent.certification_id.in_(cert_ids))
                .count()
            )

        for dog_id in set(dog_ids):
            other_team_exists = (
                db.query(Team.team_id)
                .filter(Team.dog_id == dog_id)
                .filter(~Team.team_id.in_(team_ids))
                .first()
            )
            if not other_team_exists:
                orphan_dog_ids.append(dog_id)

        affiliation_count = (
            db.query(HandlerAffiliation)
            .filter(HandlerAffiliation.handler_id == handler.handler_id)
            .count()
        )

    forum_topic_count = db.execute(
        text("SELECT COUNT(*) FROM forum_topics WHERE created_by_user_id = :uid"),
        {"uid": user_id},
    ).scalar() or 0

    forum_post_count = db.execute(
        text("SELECT COUNT(*) FROM forum_posts WHERE created_by_user_id = :uid"),
        {"uid": user_id},
    ).scalar() or 0

    email_campaign_recipient_count = db.execute(
        text("SELECT COUNT(*) FROM email_campaign_recipients WHERE user_id = :uid"),
        {"uid": user_id},
    ).scalar() or 0

    webauthn_credential_count = db.execute(
        text("SELECT COUNT(*) FROM webauthn_credentials WHERE user_id = :uid"),
        {"uid": user_id},
    ).scalar() or 0

    auth_event_count = db.execute(
        text("SELECT COUNT(*) FROM auth_events WHERE user_id = :uid"),
        {"uid": user_id},
    ).scalar() or 0

    password_reset_count = db.query(PasswordReset).filter(PasswordReset.user_id == user_id).count()
    invite_count = db.query(UserInvite).filter(UserInvite.user_id == user_id).count()

    user_role_count = db.execute(
        text("SELECT COUNT(*) FROM user_roles WHERE user_id = :uid"),
        {"uid": user_id},
    ).scalar() or 0

    user_discipline_group_count = db.execute(
        text("SELECT COUNT(*) FROM user_discipline_groups WHERE user_id = :uid"),
        {"uid": user_id},
    ).scalar() or 0

    forum_ballot_feedback_count = (
        db.query(ForumBallotFeedback)
        .filter(ForumBallotFeedback.user_id == user_id)
        .count()
    )

    forum_ballot_vote_count = (
        db.query(ForumBallotVote)
        .filter(ForumBallotVote.user_id == user_id)
        .count()
    )

    forum_topic_read_count = (
        db.query(ForumTopicRead)
        .filter(ForumTopicRead.user_id == user_id)
        .count()
    )

    expires_at = _now() + TTL_SECONDS

    hash_payload = {
        "entity": "user_tree",
        "mode": "delete_user_tree",
        "user_id": user_id,
        "handler_id": handler_id,
        "team_count": len(team_ids),
        "dog_count": len(orphan_dog_ids),
        "cert_count": len(cert_ids),
        "event_count": event_count,
        "affiliation_count": affiliation_count,
        "password_reset_count": password_reset_count,
        "invite_count": invite_count,
        "user_role_count": int(user_role_count),
        "user_discipline_group_count": int(user_discipline_group_count),
        "expires_at": expires_at,
        "forum_ballot_feedback_count": forum_ballot_feedback_count,
        "forum_ballot_vote_count": forum_ballot_vote_count,
        "forum_topic_read_count": forum_topic_read_count,
        "email_campaign_recipient_count": email_campaign_recipient_count,
        "webauthn_credential_count": webauthn_credential_count,
        "auth_event_count": auth_event_count, 
    }

    label = f"{getattr(user, 'first_name', '') or ''} {getattr(user, 'last_name', '') or ''}".strip()
    if not label:
        label = getattr(user, "email", None) or f"User {user_id}"

    warnings = [
        "Hard delete cannot be undone.",
        "This deletes the user account and login access.",
        "Only dogs that become orphaned will be deleted.",
    ]
    if forum_topic_count or forum_post_count:
        warnings.append(
            f"Forum content will be preserved: "
            f"{forum_topic_count} topics, {forum_post_count} posts."
        )
    if forum_ballot_vote_count or forum_ballot_feedback_count:
        warnings.append(
            f"Survey participation will be deleted: "
            f"{forum_ballot_vote_count} ballot votes and "
            f"{forum_ballot_feedback_count} free-form responses."
        )
    return {
        "entity": "user_tree",
        "mode": "delete_user_tree",
        "user_id": user_id,
        "handler_id": handler_id,
        "label": label,
        "will_delete": {
            "user": 1,
            "handler": 1 if handler else 0,
            "handler_affiliations": affiliation_count,
            "teams": len(team_ids),
            "dogs": len(orphan_dog_ids),
            "certifications": len(cert_ids),
            "certification_events": event_count,
            "password_resets": password_reset_count,
            "user_invites": invite_count,
            "user_roles": int(user_role_count),
            "user_discipline_groups": int(user_discipline_group_count),
            "forum_ballot_votes": db.query(ForumBallotVote)
                .filter(ForumBallotVote.user_id == user_id)
                .count(),
            "forum_ballot_feedback": db.query(ForumBallotFeedback)
                .filter(ForumBallotFeedback.user_id == user_id)
                .count(),
            "email_campaign_recipients": email_campaign_recipient_count,
            "webauthn_credentials": webauthn_credential_count,
            "auth_events": auth_event_count,
        },
        "will_preserve": {
            "forum_topics": int(forum_topic_count),
            "forum_posts": int(forum_post_count),
        },
        "sample_ids": {
            "team_ids": team_ids[:50],
            "dog_ids": orphan_dog_ids[:50],
            "certification_ids": cert_ids[:50],
        },

        "warnings": warnings,
        "blocked": False,
        "expires_at": expires_at,
        "confirm_hash": _hmac(hash_payload),
        "confirm_text_required": f"DELETE USER {user_id}",
    }


@router.post("/users/{user_id}/hard-delete-tree")
def hard_delete_user_tree(
    user_id: int,
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    _mfa=Depends(require_mfa_verified),
):
    expires_at, confirm_hash = _require_confirm(
        body,
        expected_text=f"DELETE USER {user_id}",
    )

    cu_id = getattr(current_user, "user_id", None) or getattr(current_user, "id", None)
    if cu_id and int(cu_id) == int(user_id):
        raise HTTPException(
            status_code=400,
            detail="Refusing to hard-delete the currently logged-in user.",
        )

    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    handler = db.query(Handler).filter(Handler.user_id == user_id).first()
    handler_id = handler.handler_id if handler else None

    team_ids = []
    dog_ids = []
    cert_ids = []
    orphan_dog_ids = []
    event_count = 0
    affiliation_count = 0

    if handler:
        team_ids = [
            r[0]
            for r in db.query(Team.team_id)
            .filter(Team.handler_id == handler.handler_id)
            .all()
        ]

        dog_ids = [
            r[0]
            for r in db.query(Team.dog_id)
            .filter(Team.handler_id == handler.handler_id)
            .filter(Team.dog_id.isnot(None))
            .all()
        ]

        if team_ids:
            cert_ids = [
                r[0]
                for r in db.query(Certification.certification_id)
                .filter(Certification.team_id.in_(team_ids))
                .all()
            ]

        if cert_ids:
            event_count = (
                db.query(CertificationEvent)
                .filter(CertificationEvent.certification_id.in_(cert_ids))
                .count()
            )

        for dog_id in set(dog_ids):
            other_team_exists = (
                db.query(Team.team_id)
                .filter(Team.dog_id == dog_id)
                .filter(~Team.team_id.in_(team_ids))
                .first()
            )
            if not other_team_exists:
                orphan_dog_ids.append(dog_id)

        affiliation_count = (
            db.query(HandlerAffiliation)
            .filter(HandlerAffiliation.handler_id == handler.handler_id)
            .count()
        )

    password_reset_count = (
        db.query(PasswordReset)
        .filter(PasswordReset.user_id == user_id)
        .count()
    )

    invite_count = (
        db.query(UserInvite)
        .filter(UserInvite.user_id == user_id)
        .count()
    )

    forum_ballot_feedback_count = (
        db.query(ForumBallotFeedback)
        .filter(ForumBallotFeedback.user_id == user_id)
        .count()
    )

    forum_ballot_vote_count = (
        db.query(ForumBallotVote)
        .filter(ForumBallotVote.user_id == user_id)
        .count()
    )

    forum_topic_read_count = (
        db.query(ForumTopicRead)
        .filter(ForumTopicRead.user_id == user_id)
        .count()
    )

    email_campaign_recipient_count = db.execute(
        text("SELECT COUNT(*) FROM email_campaign_recipients WHERE user_id = :uid"),
        {"uid": user_id},
    ).scalar() or 0

    webauthn_credential_count = db.execute(
        text("SELECT COUNT(*) FROM webauthn_credentials WHERE user_id = :uid"),
        {"uid": user_id},
    ).scalar() or 0

    auth_event_count = db.execute(
        text("SELECT COUNT(*) FROM auth_events WHERE user_id = :uid"),
        {"uid": user_id},
    ).scalar() or 0

    user_role_count = db.execute(
        text("SELECT COUNT(*) FROM user_roles WHERE user_id = :uid"),
        {"uid": user_id},
    ).scalar() or 0

    user_discipline_group_count = db.execute(
        text("SELECT COUNT(*) FROM user_discipline_groups WHERE user_id = :uid"),
        {"uid": user_id},
    ).scalar() or 0

    handler_headshots = handler_headshot_count(db, handler_id)
    dog_headshots = dog_headshot_count(db, orphan_dog_ids)


    expected = _hmac({
        "entity": "user_tree",
        "mode": "delete_user_tree",
        "user_id": user_id,
        "handler_id": handler_id,
        "team_count": len(team_ids),
        "dog_count": len(orphan_dog_ids),
        "cert_count": len(cert_ids),
        "event_count": event_count,
        "affiliation_count": affiliation_count,
        "password_reset_count": password_reset_count,
        "invite_count": invite_count,
        "user_role_count": int(user_role_count),
        "user_discipline_group_count": int(user_discipline_group_count),
        "expires_at": expires_at,
        "forum_ballot_feedback_count": forum_ballot_feedback_count,
        "forum_ballot_vote_count": forum_ballot_vote_count,
        "forum_topic_read_count": forum_topic_read_count,
        "email_campaign_recipient_count": email_campaign_recipient_count,
        "webauthn_credential_count": webauthn_credential_count,
        "auth_event_count": auth_event_count,
    })

    if not hmac.compare_digest(expected, confirm_hash):
        raise HTTPException(
            status_code=409,
            detail="Delete confirmation invalid. Re-run preview.",
        )

    label = f"{getattr(user, 'first_name', '') or ''} {getattr(user, 'last_name', '') or ''}".strip()
    if not label:
        label = getattr(user, "email", None) or f"User {user_id}"

    try:
        if cert_ids:
            db.query(CertificationEvent).filter(
                CertificationEvent.certification_id.in_(cert_ids)
            ).delete(synchronize_session=False)

            db.query(Certification).filter(
                Certification.certification_id.in_(cert_ids)
            ).delete(synchronize_session=False)

        if team_ids:
            db.query(Team).filter(
                Team.team_id.in_(team_ids)
            ).delete(synchronize_session=False)

        if orphan_dog_ids:
            db.query(DogIdHeadshot).filter(
                DogIdHeadshot.dog_id.in_(orphan_dog_ids)
            ).delete(synchronize_session=False)

            db.query(Dog).filter(
                Dog.dog_id.in_(orphan_dog_ids)
            ).delete(synchronize_session=False)

        if handler:
            db.query(HandlerAffiliation).filter(
                HandlerAffiliation.handler_id == handler.handler_id
            ).delete(synchronize_session=False)

            db.query(HandlerIdHeadshot).filter(
                HandlerIdHeadshot.handler_id == handler_id
            ).delete(synchronize_session=False)

            db.query(Handler).filter(
                Handler.handler_id == handler.handler_id
            ).delete(synchronize_session=False)

        db.query(PasswordReset).filter(
            PasswordReset.user_id == user_id
        ).delete(synchronize_session=False)

        db.query(UserInvite).filter(
            UserInvite.user_id == user_id
        ).delete(synchronize_session=False)

        db.execute(
            text("DELETE FROM user_discipline_groups WHERE user_id = :uid"),
            {"uid": user_id},
        )

        db.execute(
            text("DELETE FROM user_roles WHERE user_id = :uid"),
            {"uid": user_id},
        )

        # Add these only if the tables exist in your schema.
        db.execute(
            text("DELETE FROM webauthn_credentials WHERE user_id = :uid"),
            {"uid": user_id},
        )

        db.execute(
            text("DELETE FROM auth_events WHERE user_id = :uid"),
            {"uid": user_id},
        )

        db.execute(
            text("DELETE FROM email_campaign_recipients WHERE user_id = :uid"),
            {"uid": user_id},
        )

        db.query(ForumBallotFeedback).filter(
            ForumBallotFeedback.user_id == user_id
        ).delete(synchronize_session=False)

        db.query(ForumBallotVote).filter(
            ForumBallotVote.user_id == user_id
        ).delete(synchronize_session=False)

        db.query(ForumTopicRead).filter(
            ForumTopicRead.user_id == user_id
        ).delete(synchronize_session=False)

        log_cleanup_event(
            db,
            actor_user_id=current_user.user_id,
            action="hard_delete_user_tree",
            entity_type="user",
            entity_id=user_id,
            entity_label=label,
            deleted_counts={
                "user": 1,
                "handler": 1 if handler else 0,
                "handler_affiliations": affiliation_count,
                "teams": len(team_ids),
                "dogs": len(orphan_dog_ids),
                "certifications": len(cert_ids),
                "certification_events": event_count,
                "password_resets": password_reset_count,
                "user_invites": invite_count,
                "user_roles": int(user_role_count),
                "user_discipline_groups": int(user_discipline_group_count),
                "forum_ballot_feedback": forum_ballot_feedback_count,
                "forum_ballot_votes": forum_ballot_vote_count,
                "forum_topic_reads": forum_topic_read_count,
                "email_campaign_recipients": int(email_campaign_recipient_count),
                "webauthn_credentials": int(webauthn_credential_count),
                "auth_events": int(auth_event_count),
                "handler_headshots": handler_headshots,
                "dog_headshots": dog_headshots,
            },
            affected_ids={
                "user_ids": [user_id],
                "handler_ids": [handler_id] if handler_id else [],
                "team_ids": team_ids,
                "dog_ids": orphan_dog_ids,
                "certification_ids": cert_ids,
            },
            warnings=[
                "User account was hard-deleted.",
                "Forum posts/topics were preserved.",
                "Forum votes, feedback, and read-tracking rows for this user were deleted.",
            ],
            confirmation_text=f"DELETE USER {user_id}",
        )

        db.delete(user)

        db.commit()

        return {
            "status": "deleted",
            "user_id": user_id,
            "handler_id": handler_id,
            "teams": len(team_ids),
            "dogs": len(orphan_dog_ids),
            "certifications": len(cert_ids),
            "certification_events": event_count,
            "handler_headshots": handler_headshots,
            "dog_headshots": dog_headshots, 
        }

    except Exception:
        db.rollback()
        raise

def topic_tree_hash_payload(
    *,
    topic_id: int,
    title: str,
    category_id: int,
    will_delete: dict,
    confirm_text_required: str,
    expires_at: int,
):
    return {
        "entity": "topic_survey_tree",
        "mode": "delete_topic_tree",
        "topic_id": topic_id,
        "title": title,
        "category_id": category_id,
        "will_delete": will_delete,
        "confirm_text_required": confirm_text_required,
        "expires_at": expires_at,
    }

def preview_topic_tree(db: Session, topic_id: int):
    topic = db.query(ForumTopic).filter(ForumTopic.topic_id == topic_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    ballot_ids = [
        x[0]
        for x in (
            db.query(ForumBallot.ballot_id)
            .filter(ForumBallot.topic_id == topic_id)
            .all()
        )
    ]

    post_ids = [
        x[0]
        for x in (
            db.query(ForumPost.post_id)
            .filter(ForumPost.topic_id == topic_id)
            .all()
        )
    ]

    forum_ballot_choices = (
        db.query(ForumBallotChoice)
        .filter(ForumBallotChoice.ballot_id.in_(ballot_ids))
        .count()
        if ballot_ids
        else 0
    )

    forum_ballot_votes = (
        db.query(ForumBallotVote)
        .filter(ForumBallotVote.ballot_id.in_(ballot_ids))
        .count()
        if ballot_ids
        else 0
    )

    forum_ballot_feedback = (
        db.query(ForumBallotFeedback)
        .filter(ForumBallotFeedback.ballot_id.in_(ballot_ids))
        .count()
        if ballot_ids
        else 0
    )

    forum_topic_reads = (
        db.query(ForumTopicRead)
        .filter(ForumTopicRead.topic_id == topic_id)
        .count()
    )

    will_delete = {
        "forum_topics": 1,
        "forum_posts": len(post_ids),
        "forum_ballots": len(ballot_ids),
        "forum_ballot_choices": forum_ballot_choices,
        "forum_ballot_votes": forum_ballot_votes,
        "forum_ballot_feedback": forum_ballot_feedback,
        "forum_topic_reads": forum_topic_reads,
    }

    expires_at = _now() + TTL_SECONDS
    confirm_text_required = f"DELETE TOPIC {topic.topic_id}"

    hash_payload = topic_tree_hash_payload(
        topic_id=topic.topic_id,
        title=topic.title,
        category_id=topic.category_id,
        will_delete=will_delete,
        confirm_text_required=confirm_text_required,
        expires_at=expires_at,
    )

    return {
        "entity": "topic_survey_tree",
        "mode": "delete_topic_tree",
        "topic_id": topic.topic_id,
        "label": f"Topic / Survey Tree: {topic.title}",
        "title": topic.title,
        "category_id": topic.category_id,
        "will_delete": will_delete,
        "sample_ids": {
            "ballot_ids": ballot_ids[:10],
            "post_ids": post_ids[:10],
        },
        "expires_at": expires_at,
        "confirm_hash": _hmac(hash_payload),
        "confirm_text_required": confirm_text_required,
    }

@router.get("/topic-tree/{topic_id}/preview")
def preview_topic_cleanup(
    topic_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    #_mfa=Depends(require_mfa_verified),
):
    return preview_topic_tree(db, topic_id)


@router.post("/topic-tree/{topic_id}/hard-delete-tree")
def delete_topic_cleanup(
    topic_id: int,
    payload: CleanupConfirmIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    _mfa=Depends(require_mfa_verified),
):
    if payload.expires_at < _now():
        raise HTTPException(status_code=400, detail="Confirmation expired")

    preview = preview_topic_tree(db, topic_id)

    expected_text = f"DELETE TOPIC {topic_id}"

    if payload.confirm_text != expected_text:
        raise HTTPException(status_code=400, detail="Confirmation text does not match")

    hash_payload = topic_tree_hash_payload(
        topic_id=preview["topic_id"],
        title=preview["title"],
        category_id=preview["category_id"],
        will_delete=preview["will_delete"],
        confirm_text_required=expected_text,
        expires_at=payload.expires_at,
    )

    if payload.confirm_hash != _hmac(hash_payload):
        raise HTTPException(status_code=400, detail="Invalid confirmation hash")

    ballot_ids = [
        x[0]
        for x in (
            db.query(ForumBallot.ballot_id)
            .filter(ForumBallot.topic_id == topic_id)
            .all()
        )
    ]

    if ballot_ids:
        db.query(ForumBallotFeedback).filter(
            ForumBallotFeedback.ballot_id.in_(ballot_ids)
        ).delete(synchronize_session=False)

        db.query(ForumBallotVote).filter(
            ForumBallotVote.ballot_id.in_(ballot_ids)
        ).delete(synchronize_session=False)

        db.query(ForumBallotChoice).filter(
            ForumBallotChoice.ballot_id.in_(ballot_ids)
        ).delete(synchronize_session=False)

    db.query(ForumBallot).filter(
        ForumBallot.topic_id == topic_id
    ).delete(synchronize_session=False)

    db.query(ForumTopicRead).filter(
        ForumTopicRead.topic_id == topic_id
    ).delete(synchronize_session=False)

    db.query(ForumPost).filter(
        ForumPost.topic_id == topic_id
    ).delete(synchronize_session=False)

    db.query(ForumTopic).filter(
        ForumTopic.topic_id == topic_id
    ).delete(synchronize_session=False)

    db.commit()

    return {
        "status": "deleted",
        "entity": "topic_survey_tree",
        "topic_id": topic_id,
    }


# ---------- STANDARD hard delete (BLOCK if referenced) ----------
@router.get("/standards/{standard_id}/delete-preview")
def preview_delete_standard(standard_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin), _mfa=Depends(require_mfa_verified)):

    std = db.query(Standard).filter(Standard.standard_id == standard_id).first()
    if not std:
        raise HTTPException(status_code=404, detail="Standard not found")

    cert_count = db.query(Certification).filter(Certification.standard_id == standard_id).count()

    expires_at = _now() + TTL_SECONDS
    hash_payload = {
        "entity": "standard",
        "standard_id": standard_id,
        "cert_count": cert_count,
        "expires_at": expires_at,
    }
    return {
        "entity": "standard",
        "standard_id": standard_id,
        "label": std.name,
        "will_delete": {"standard_row": 1, "certifications_referencing": cert_count},
        "warnings": (
            ["Hard delete cannot be undone."]
            + (["DELETE WILL BE BLOCKED because certifications reference this standard."] if cert_count > 0 else [])
        ),
        "blocked": cert_count > 0,
        "expires_at": expires_at,
        "confirm_hash": _hmac(hash_payload),
        "confirm_text_required": f"DELETE STANDARD {standard_id}",
    }

@router.post("/standards/{standard_id}/hard-delete")
def hard_delete_standard(standard_id: int, body: dict, db: Session = Depends(get_db), current_user: User = Depends(require_admin), _mfa=Depends(require_mfa_verified)):

    expires_at, confirm_hash = _require_confirm(body, expected_text=f"DELETE STANDARD {standard_id}")

    cert_count = db.query(Certification).filter(Certification.standard_id == standard_id).count()
    if cert_count > 0:
        raise HTTPException(status_code=409, detail="Cannot delete standard: certifications reference it.")

    expected = _hmac({"entity": "standard", "standard_id": standard_id, "cert_count": cert_count, "expires_at": expires_at})
    if not hmac.compare_digest(expected, confirm_hash):
        raise HTTPException(status_code=409, detail="Delete confirmation invalid. Re-run preview.")

    std = db.query(Standard).filter(Standard.standard_id == standard_id).first()
    if not std:
        raise HTTPException(status_code=404, detail="Standard not found")

    try:
        db.delete(std)
        db.commit()
        return {"status": "deleted", "standard_id": standard_id}
    except Exception:
        db.rollback()
        raise

# ---------- DISCIPLINE hard delete (BLOCK if any cert under its standards) ----------
@router.get("/disciplines/{discipline_id}/delete-preview")
def preview_delete_discipline(discipline_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_admin), _mfa=Depends(require_mfa_verified)):

    d = db.query(Discipline).filter(Discipline.discipline_id == discipline_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Discipline not found")

    standards_count = db.query(Standard).filter(Standard.discipline_id == discipline_id).count()
    cert_count = (
        db.query(func.count(Certification.certification_id))
        .join(Standard, Standard.standard_id == Certification.standard_id)
        .filter(Standard.discipline_id == discipline_id)
        .scalar()
        or 0
    )

    expires_at = _now() + TTL_SECONDS
    hash_payload = {
        "entity": "discipline",
        "discipline_id": discipline_id,
        "standards_count": standards_count,
        "cert_count": int(cert_count),
        "expires_at": expires_at,
    }
    blocked = cert_count > 0
    return {
        "entity": "discipline",
        "discipline_id": discipline_id,
        "label": d.name,
        "will_delete": {"discipline_row": 1, "standards": standards_count, "certifications_referencing_standards": int(cert_count)},
        "warnings": (
            ["Hard delete cannot be undone."]
            + (["DELETE WILL BE BLOCKED because certifications exist under this discipline."] if blocked else [])
        ),
        "blocked": blocked,
        "expires_at": expires_at,
        "confirm_hash": _hmac(hash_payload),
        "confirm_text_required": f"DELETE DISCIPLINE {discipline_id}",
    }

@router.post("/disciplines/{discipline_id}/hard-delete")
def hard_delete_discipline(discipline_id: int, body: dict, db: Session = Depends(get_db), current_user: User = Depends(require_admin), _mfa=Depends(require_mfa_verified)):

    expires_at, confirm_hash = _require_confirm(body, expected_text=f"DELETE DISCIPLINE {discipline_id}")

    standards_count = db.query(Standard).filter(Standard.discipline_id == discipline_id).count()
    cert_count = (
        db.query(func.count(Certification.certification_id))
        .join(Standard, Standard.standard_id == Certification.standard_id)
        .filter(Standard.discipline_id == discipline_id)
        .scalar()
        or 0
    )

    if cert_count > 0:
        raise HTTPException(status_code=409, detail="Cannot delete discipline: certifications exist under its standards.")

    expected = _hmac({
        "entity": "discipline",
        "discipline_id": discipline_id,
        "standards_count": standards_count,
        "cert_count": int(cert_count),
        "expires_at": expires_at,
    })
    if not hmac.compare_digest(expected, confirm_hash):
        raise HTTPException(status_code=409, detail="Delete confirmation invalid. Re-run preview.")

    d = db.query(Discipline).filter(Discipline.discipline_id == discipline_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Discipline not found")

    try:
        db.delete(d)  # cascades standards (ORM + DB), safe because cert_count == 0
        db.commit()
        return {"status": "deleted", "discipline_id": discipline_id}
    except Exception:
        db.rollback()
        raise


@router.delete("/users/{user_id}/hard", status_code=204)
def hard_delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
    _mfa=Depends(require_mfa_verified),  # <-- add this
):

    # Prevent accidental self-nuke (optional but recommended)
    cu_id = getattr(current_user, "user_id", None) or getattr(current_user, "id", None)
    if cu_id and int(cu_id) == int(user_id):
        raise HTTPException(status_code=400, detail="Refusing to hard-delete the currently logged-in user.")

    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    handler = db.query(Handler).filter(Handler.user_id == user_id).first()

    # If you allow users without handlers, handler can be None
    team_ids: list[int] = []
    dog_ids: list[int] = []

    if handler:
        teams = db.query(Team).filter(Team.handler_id == handler.handler_id).all()
        team_ids = [t.team_id for t in teams]
        dog_ids = list({t.dog_id for t in teams if getattr(t, "dog_id", None) is not None})

    try:
        # Transaction
        # 1) certifications for those teams
        if team_ids:
            db.query(Certification).filter(Certification.team_id.in_(team_ids)).delete(synchronize_session=False)

        # 2) teams
        if team_ids:
            db.query(Team).filter(Team.team_id.in_(team_ids)).delete(synchronize_session=False)

        # 3) user-linked rows (these reference users.user_id)
        db.query(PasswordReset).filter(PasswordReset.user_id == user_id).delete(synchronize_session=False)
        db.query(UserInvite).filter(UserInvite.user_id == user_id).delete(synchronize_session=False)
        db.execute(
            text("DELETE FROM user_discipline_groups WHERE user_id = :uid"),
            {"uid": user_id},
        )
        db.execute(
            text("DELETE FROM email_campaign_recipients WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        db.execute(
            text("DELETE FROM user_roles WHERE user_id = :uid"),
            {"uid": user_id},
        )
        # 4) handler
        if handler:
            db.delete(handler)

        # 5) user
        db.delete(user)

        # 6) delete dogs only if orphaned (no teams reference them anymore)
        # Dogs can be on multiple teams, so only remove those that now have no Team rows.
        if dog_ids:
            for dog_id in dog_ids:
                still_used = db.query(
                    exists().where(Team.dog_id == dog_id)
                ).scalar()
                if not still_used:
                    dog = db.query(Dog).filter(Dog.dog_id == dog_id).first()
                    if dog:
                        db.query(DogIdHeadshot).filter(
                            DogIdHeadshot.dog_id == dog_id
                            ).delete(synchronize_session=False)
                        db.delete(dog)

        db.commit()
        return

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Hard delete failed: {e}")


@router.get("/cleanup/audit")
def list_cleanup_audit(
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    _mfa=Depends(require_mfa_verified),
):
    rows = (
        db.query(AdminCleanupEvent)
        .order_by(AdminCleanupEvent.created_at.desc())
        .limit(min(limit, 500))
        .all()
    )

    return [
        {
            "cleanup_event_id": r.cleanup_event_id,
            "created_at": r.created_at,
            "actor_user_id": r.actor_user_id,
            "actor_email": r.actor_email,
            "actor_name": r.actor_name,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "entity_label": r.entity_label,
            "deleted_counts": r.deleted_counts_json or {},
            "affected_ids": r.affected_ids_json or {},
            "warnings": r.warnings_json or [],
            "confirmation_text": r.confirmation_text,
        }
        for r in rows
    ]

@router.get("/certificates/{certification_id}/preview")
def preview_certificate_delete(
    certification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    _mfa=Depends(require_mfa_verified),
):
    cert = (
        db.query(Certification)
        .filter(Certification.certification_id == certification_id)
        .first()
    )

    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")

    team = db.query(Team).filter(Team.team_id == cert.team_id).first()
    handler = (
        db.query(Handler).filter(Handler.handler_id == team.handler_id).first()
        if team else None
    )

    handler_user = (
        db.query(User).filter(User.user_id == handler.user_id).first()
        if handler and handler.user_id
        else None
    )

    dog = (
        db.query(Dog).filter(Dog.dog_id == team.dog_id).first()
        if team else None
    )
    standard = db.query(Standard).filter(Standard.standard_id == cert.standard_id).first()

    evaluator = (
        db.query(User).filter(User.user_id == cert.issuer_user_id).first()
        if cert.issuer_user_id else None
    )

    history_count = (
        db.query(CertificationEvent)
        .filter(CertificationEvent.certification_id == certification_id)
        .count()
    )

    expires_at = _now() + TTL_SECONDS

    hash_payload = {
        "entity": "certificate",
        "certification_id": certification_id,
        "history_count": history_count,
        "expires_at": expires_at,
    }

    handler_name = (
        f"{handler_user.first_name} {handler_user.last_name}".strip()
        if handler_user
        else "Unknown handler"
    )

    evaluator_name = (
        f"{evaluator.first_name} {evaluator.last_name}".strip()
        if evaluator
        else "Unknown evaluator"
    )

    dog_name = dog.name if dog else "Unknown dog"
    standard_name = standard.name if standard else "Unknown standard"

    label = f"Certificate {certification_id}: {handler_name} / {dog_name} / {standard_name} evaluated by {evaluator_name}"

    return {
        "entity": "certificate",
        "certificate_id": certification_id,
        "certification_id": certification_id,
        "team_id": cert.team_id,
        "label": label,

        "will_delete": {
            "certification": 1,
            "certification_events": history_count,
            "certificate_signatures": 0,
        },

        "sample_ids": {
            "certification_ids": [certification_id],
            "team_ids": [cert.team_id] if cert.team_id else [],
        },

        "warnings": [
            "Hard delete cannot be undone.",
            "This removes the certificate record and its certification audit events.",
            "Certificate signature snapshot deletion is not active yet because that model is not wired in.",
        ],

        "handler_name": handler_name,
        "dog_name": dog_name,
        "standard_name": standard_name,
        "status": cert.status,
        "date_awarded": cert.date_awarded,
        "expires_at_value": cert.expires_at,
        "location": cert.location,
        "comment": cert.comment,
        "evaluator_name": evaluator_name,

        "blocked": False,
        "expires_at": expires_at,
        "confirm_hash": _hmac(hash_payload),
        "confirm_text_required": f"DELETE CERTIFICATE {certification_id}",
    }

@router.post("/certificates/{certification_id}/hard-delete")
def hard_delete_certificate(
    certification_id: int,
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    _mfa=Depends(require_mfa_verified),
):
    expires_at, confirm_hash = _require_confirm(
        body,
        expected_text=f"DELETE CERTIFICATE {certification_id}",
    )

    cert = (
        db.query(Certification)
        .filter(Certification.certification_id == certification_id)
        .first()
    )

    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")

    history_count = (
        db.query(CertificationEvent)
        .filter(CertificationEvent.certification_id == certification_id)
        .count()
    )

    expected = _hmac({
        "entity": "certificate",
        "certification_id": certification_id,
        "history_count": history_count,
        "expires_at": expires_at,
    })

    if not hmac.compare_digest(expected, confirm_hash):
        raise HTTPException(
            status_code=409,
            detail="Delete confirmation invalid. Re-run preview.",
        )

    try:
        db.query(CertificationEvent).filter(
            CertificationEvent.certification_id == certification_id
        ).delete(synchronize_session=False)

        db.query(Certification).filter(
            Certification.certification_id == certification_id
        ).delete(synchronize_session=False)

        log_cleanup_event(
            db,
            actor_user_id=current_user.user_id,
            action="hard_delete_certificate",
            entity_type="certificate",
            entity_id=certification_id,
            entity_label=f"Certificate {certification_id}",
            deleted_counts={
                "certifications": 1,
                "certification_events": history_count,
                "certificate_signatures": 0,
            },
            affected_ids={
                "certification_ids": [certification_id],
                "team_ids": [cert.team_id] if cert.team_id else [],
            },
            warnings=[
                "Certificate and certification events were hard-deleted.",
                "Certificate signature snapshots were not deleted because that model is not wired in yet.",
            ],
            confirmation_text=f"DELETE CERTIFICATE {certification_id}",
        )
 
        db.commit()
 
        return {
            "status": "deleted",
            "certificate_id": certification_id,
            "certification_events": history_count,
        }

    except Exception:
        db.rollback()
        raise

    