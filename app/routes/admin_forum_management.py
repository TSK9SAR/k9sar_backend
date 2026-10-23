"""Administrator category and topic management; no schema migration required."""
import hashlib
import hmac
import json
import logging
import os
import re
import time
import unicodedata
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.forum import (ForumBallot, ForumBallotChoice, ForumBallotVote,
                              ForumBallotFeedback, ForumCategory, ForumPost,
                              ForumTopic, ForumTopicRead)
from app.models.stored_files import ForumPostAttachment, StoredFile, EmailCampaignAttachment
from app.services.stored_files import delete_physical_file
from app.utils.auth import require_admin, require_mfa_verified

router = APIRouter(prefix="/admin/forum", tags=["Forum management"], dependencies=[Depends(require_admin)])
write_access = [Depends(require_mfa_verified)]
CATEGORY_FIELDS = ("name", "description", "sortorder", "is_active", "min_role", "notify_default")
logger = logging.getLogger(__name__)


class CategoryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=5000)
    sortorder: int = Field(default=0, ge=-100000, le=100000)
    is_active: StrictBool = True
    min_role: Literal["member", "evaluator", "supervisor", "admin"] = "member"
    notify_default: Literal["all", "announcements", "none"] = "none"

    @field_validator("name", "description", mode="before")
    @classmethod
    def trim_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class CategoryUpdate(CategoryIn):
    expected_revision: str = Field(min_length=64, max_length=64)


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation_token: str = Field(min_length=1, max_length=100)


class DeleteConfirmation(Confirmation):
    confirm_text: str = Field(max_length=140)


class MoveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    destination_category_id: int = Field(gt=0)


class MoveConfirmation(MoveIn, Confirmation):
    pass


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _category_state(category):
    return {"category_id": category.category_id, **{field: getattr(category, field) for field in CATEGORY_FIELDS}}


def _category_out(category, count=0):
    state = _category_state(category)
    return {**state, "description": category.description or "", "topic_count": count, "revision": _digest(state)}


def _category(db, category_id, *, lock=False):
    query = db.query(ForumCategory).filter(ForumCategory.category_id == category_id)
    if lock:
        query = query.with_for_update()
    category = query.first()
    if category is None:
        raise HTTPException(404, "Category not found.")
    return category


def _topic_count(db, category_id):
    return db.query(ForumTopic).filter(ForumTopic.category_id == category_id).count()


def _signature(actor_id, action, state, expires):
    secret = os.getenv("JWT_SECRET_KEY") or os.getenv("JWT_SECRET") or os.getenv("SECRET_KEY")
    if not secret:
        raise HTTPException(503, "Forum confirmation signing is unavailable.")
    message = json.dumps(["forum-management-v1", actor_id, action, state, expires], sort_keys=True, separators=(",", ":"))
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def _preview(actor, action, state):
    expires = int(time.time()) + 300
    return {**state, "expires_at": expires,
            "confirmation_token": f"{expires}.{_signature(actor.user_id, action, state, expires)}"}


def _verify(token, actor, action, state):
    if not re.fullmatch(r"[0-9]{1,12}\.[0-9a-f]{64}", token):
        raise HTTPException(409, "Invalid confirmation. Review the action again.")
    try:
        raw_expiry, signature = token.split(".", 1)
        expires = int(raw_expiry)
    except (ValueError, AttributeError):
        raise HTTPException(409, "Invalid confirmation. Review the action again.")
    if expires <= int(time.time()) or expires > int(time.time()) + 300:
        raise HTTPException(409, "Confirmation expired. Review the action again.")
    if not hmac.compare_digest(signature, _signature(actor.user_id, action, state, expires)):
        raise HTTPException(409, "The forum changed or this confirmation is invalid. Review the action again.")


@router.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    rows = (db.query(ForumCategory, func.count(ForumTopic.topic_id))
            .outerjoin(ForumTopic, ForumTopic.category_id == ForumCategory.category_id)
            .group_by(ForumCategory.category_id)
            .order_by(ForumCategory.sortorder, ForumCategory.name, ForumCategory.category_id).all())
    return [_category_out(category, count) for category, count in rows]


@router.post("/categories", status_code=201, dependencies=write_access)
def create_category(body: CategoryIn, db: Session = Depends(get_db)):
    slug = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", body.name).encode("ascii", "ignore").decode().lower()).strip("-")[:100] or "category"
    # Keep slugs stable across renames; IDs are used by all public forum links.
    base, suffix = slug, 2
    while db.query(ForumCategory.category_id).filter(ForumCategory.slug == slug).first():
        slug = f"{base}-{suffix}"
        suffix += 1
    category = ForumCategory(**body.model_dump(), slug=slug)
    db.add(category)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A category was created concurrently. Please try again.")
    db.refresh(category)
    return _category_out(category)


@router.put("/categories/{category_id}", dependencies=write_access)
def update_category(category_id: int, body: CategoryUpdate, db: Session = Depends(get_db)):
    category = _category(db, category_id, lock=True)
    if body.expected_revision != _digest(_category_state(category)):
        raise HTTPException(409, "This category was changed by another administrator. Reload it before saving.")
    for field in CATEGORY_FIELDS:
        setattr(category, field, getattr(body, field))
    db.commit()
    db.refresh(category)
    return _category_out(category, _topic_count(db, category_id))


def _delete_state(db, category_id, *, lock=False):
    category = _category(db, category_id, lock=lock)
    if _topic_count(db, category_id):
        raise HTTPException(409, "This category contains topics. Move them first, or hide the category instead.")
    return {"category": _category_out(category), "confirm_text": f"DELETE {category.name}"}


@router.post("/categories/{category_id}/delete-preview", dependencies=write_access)
def delete_preview(category_id: int, db: Session = Depends(get_db), actor=Depends(require_admin)):
    return _preview(actor, "delete-category", _delete_state(db, category_id))


@router.post("/categories/{category_id}/delete-confirm", dependencies=write_access)
def delete_category(category_id: int, body: DeleteConfirmation, db: Session = Depends(get_db), actor=Depends(require_admin)):
    state = _delete_state(db, category_id, lock=True)
    _verify(body.confirmation_token, actor, "delete-category", state)
    if body.confirm_text != state["confirm_text"]:
        raise HTTPException(400, "The confirmation text does not match.")
    try:
        # Direct DELETE plus the FK constraint protects against concurrent topic creation.
        db.query(ForumCategory).filter(ForumCategory.category_id == category_id).delete(synchronize_session=False)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "The category now contains topics and cannot be deleted.")
    return {"deleted_category_id": category_id}


@router.get("/topics")
def list_topics(q: str = Query(default="", max_length=200), category_id: int | None = None,
                topic_id: int | None = None, offset: int = Query(default=0, ge=0),
                limit: int = Query(default=25, ge=1, le=100), db: Session = Depends(get_db)):
    query = db.query(ForumTopic, ForumCategory).join(ForumCategory, ForumCategory.category_id == ForumTopic.category_id)
    if category_id is not None:
        query = query.filter(ForumTopic.category_id == category_id)
    if topic_id is not None:
        query = query.filter(ForumTopic.topic_id == topic_id)
    if q.strip():
        query = query.filter(ForumTopic.title.contains(q.strip(), autoescape=True))
    total = query.count()
    rows = query.order_by(ForumTopic.last_post_at.desc(), ForumTopic.topic_id.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": [{"topic_id": t.topic_id, "title": t.title,
            "category_id": c.category_id, "category_name": c.name, "category_active": c.is_active,
            "is_locked": t.is_locked, "is_pinned": t.is_pinned} for t, c in rows]}


def _move_state(db, topic_id, destination_id, *, lock=False):
    query = db.query(ForumTopic).filter(ForumTopic.topic_id == topic_id)
    topic = (query.with_for_update() if lock else query).first()
    if topic is None:
        raise HTTPException(404, "Topic not found.")
    if topic.category_id == destination_id:
        raise HTTPException(400, "Choose a different destination category.")
    categories = {cid: _category(db, cid, lock=lock) for cid in sorted({topic.category_id, destination_id})}
    source, destination = categories[topic.category_id], categories[destination_id]
    if not destination.is_active:
        raise HTTPException(409, "The destination category is hidden. Show it before moving a topic into it.")
    post_count = db.query(ForumPost).filter(ForumPost.topic_id == topic_id).count()
    poll_count = db.query(ForumBallot).filter(ForumBallot.topic_id == topic_id).count()
    attachment_count = (db.query(ForumPostAttachment).join(ForumPost, ForumPost.post_id == ForumPostAttachment.post_id)
                        .filter(ForumPost.topic_id == topic_id).count())
    return topic, {"topic_id": topic_id, "title": topic.title,
                   "source": _category_state(source), "destination": _category_state(destination),
                   "post_count": post_count, "poll_count": poll_count, "attachment_count": attachment_count}


@router.post("/topics/{topic_id}/move-preview", dependencies=write_access)
def move_preview(topic_id: int, body: MoveIn, db: Session = Depends(get_db), actor=Depends(require_admin)):
    _, state = _move_state(db, topic_id, body.destination_category_id)
    return _preview(actor, "move-topic", state)


@router.post("/topics/{topic_id}/move-confirm", dependencies=write_access)
def move_topic(topic_id: int, body: MoveConfirmation, db: Session = Depends(get_db), actor=Depends(require_admin)):
    topic, state = _move_state(db, topic_id, body.destination_category_id, lock=True)
    _verify(body.confirmation_token, actor, "move-topic", state)
    topic.category_id = body.destination_category_id
    # No copying or deletion: posts, polls, attachments, read state, and email links retain their IDs.
    db.commit()
    return {"topic_id": topic_id, "category_id": body.destination_category_id, "category_name": state["destination"]["name"]}


def _topic_delete_state(db, topic_id):
    # Lock parents before children. FK checks block new children while confirmation
    # is in progress. Locking reads also avoid an older MySQL transaction snapshot.
    topic = db.query(ForumTopic).filter(ForumTopic.topic_id == topic_id).populate_existing().with_for_update().first()
    if topic is None:
        raise HTTPException(404, "Topic not found.")
    category = _category(db, topic.category_id, lock=True)

    def rows(model, condition):
        return (db.query(model).filter(condition).order_by(*model.__table__.primary_key.columns)
                .populate_existing().with_for_update().all())

    posts = rows(ForumPost, ForumPost.topic_id == topic_id)
    polls = rows(ForumBallot, ForumBallot.topic_id == topic_id)
    post_ids = [post.post_id for post in posts]
    poll_ids = [poll.ballot_id for poll in polls]
    groups = [
        (ForumBallotFeedback, rows(ForumBallotFeedback, ForumBallotFeedback.ballot_id.in_(poll_ids))),
        (ForumBallotVote, rows(ForumBallotVote, ForumBallotVote.ballot_id.in_(poll_ids))),
        (ForumBallotChoice, rows(ForumBallotChoice, ForumBallotChoice.ballot_id.in_(poll_ids))),
        (ForumBallot, polls),
        (ForumPostAttachment, rows(ForumPostAttachment, ForumPostAttachment.post_id.in_(post_ids))),
        (ForumPost, posts),
    ]

    def record(row):
        # Include contents, IDs and timestamps, so same-count replacements and
        # edits within a single timestamp second invalidate the reviewed state.
        values = {col.name: getattr(row, col.name) for col in row.__table__.columns}
        return {key: value.isoformat() if hasattr(value, "isoformat") else value for key, value in values.items()}

    revision = _digest([record(topic), *[[record(row) for row in records] for _, records in groups]])
    state = {"topic_id": topic_id, "title": topic.title, "category": _category_state(category),
             "post_count": len(posts), "poll_count": len(polls),
             "vote_count": len(groups[1][1]), "feedback_count": len(groups[0][1]),
             "attachment_count": len(groups[4][1]), "content_revision": revision,
             "confirm_text": f"DELETE TOPIC {topic_id}"}
    return state, groups


@router.post("/topics/{topic_id}/delete-preview", dependencies=write_access)
def topic_delete_preview(topic_id: int, db: Session = Depends(get_db), actor=Depends(require_admin)):
    state, _ = _topic_delete_state(db, topic_id)
    return _preview(actor, "delete-topic", state)


@router.post("/topics/{topic_id}/delete-confirm", dependencies=write_access)
def delete_topic(topic_id: int, body: DeleteConfirmation, db: Session = Depends(get_db), actor=Depends(require_admin)):
    state, groups = _topic_delete_state(db, topic_id)
    _verify(body.confirmation_token, actor, "delete-topic", state)
    if body.confirm_text != state["confirm_text"]:
        raise HTTPException(400, "The confirmation text does not match.")

    file_ids = sorted({link.file_id for link in groups[4][1]})
    files = (db.query(StoredFile).filter(StoredFile.file_id.in_(file_ids))
             .order_by(StoredFile.file_id).with_for_update().all())
    physical_files = []
    try:
        # Explicit child-first deletion preserves unrelated discussions and avoids
        # depending on undocumented database/ORM cascades.
        for model, records in groups:
            pk = list(model.__table__.primary_key.columns)[0]
            if records:
                db.query(model).filter(pk.in_([getattr(row, pk.name) for row in records])).delete(synchronize_session=False)
        db.query(ForumTopicRead).filter(ForumTopicRead.topic_id == topic_id).delete(synchronize_session=False)
        db.query(ForumTopic).filter(ForumTopic.topic_id == topic_id).delete(synchronize_session=False)

        for stored in files:
            # Current reads plus the locked file row protect shared attachments,
            # including files used in email campaigns, from concurrent linking.
            forum_ref = (db.query(ForumPostAttachment.attachment_id)
                         .filter(ForumPostAttachment.file_id == stored.file_id).with_for_update().first())
            campaign_ref = (db.query(EmailCampaignAttachment.attachment_id)
                            .filter(EmailCampaignAttachment.file_id == stored.file_id).with_for_update().first())
            if forum_ref is None and campaign_ref is None:
                physical_files.append((stored.file_id, stored.storage_path))
                db.delete(stored)
        # ForumEmailReceipt deliberately survives deletion to prevent email replay.
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "The discussion changed or still has related content. Review it again before deleting.")

    cleanup_pending = 0
    for file_id, storage_path in physical_files:
        try:
            delete_physical_file(storage_path)
        except (OSError, ValueError, RuntimeError):
            # Do not report a failed deletion after the database already committed.
            cleanup_pending += 1
            logger.warning("Topic deleted; physical cleanup pending for stored file id=%s", file_id)
    return {"deleted_topic_id": topic_id, "category_id": state["category"]["category_id"],
            "stored_files_deleted": len(physical_files), "file_cleanup_pending": cleanup_pending}
