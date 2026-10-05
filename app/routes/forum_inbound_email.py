"""Authenticated Cloudflare ingress; never an alternative interactive login."""
import hashlib
import hmac
import os
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from app.database import get_db
from app.models.forum import ForumEmailReceipt, ForumPost, ForumTopic
from app.models.user import User
from app.routes.forum import _require_category_access, _is_admin, _next_sort_order
from app.services.forum_email_replies import (
    MAX_RAW_BYTES, decode_recipient, parse_reply, reply_config, verify_reply_token,
)
from app.services.forum_notifications import send_new_reply_notifications

router = APIRouter(prefix="/api/forums", tags=["Forum"])


def accept_reply(db, raw, sender, recipient, secret, domain, background_tasks):
    try:
        user_id, topic_id, token = decode_recipient(recipient, domain)
        user = db.query(User).filter(User.user_id == user_id, User.is_active == True).first()
        if not user:
            raise ValueError("Invalid forum reply address")
        verify_reply_token(token, user.email, secret)
        body, identity = parse_reply(raw, sender, user.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    # Serialize inbound replies to this topic, including duplicate delivery.
    topic = db.query(ForumTopic).filter(ForumTopic.topic_id == topic_id).with_for_update().first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    _require_category_access(user, topic.category)
    if topic.is_locked and not _is_admin(user):
        raise HTTPException(status_code=403, detail="Topic is locked")

    key = hashlib.sha256(f"{user_id}:{topic_id}:{identity}".encode()).hexdigest()
    existing = db.get(ForumEmailReceipt, key)
    if existing:
        return {"ok": True, "duplicate": True, "post_id": existing.post_id}
    post = ForumPost(topic_id=topic_id, body_md=body, post_type="comment",
                     sort_order=_next_sort_order(db, topic_id), created_by_user_id=user_id)
    db.add(post)
    topic.last_post_at = datetime.now(timezone.utc)
    try:
        db.flush()
        post_id = post.post_id
        db.add(ForumEmailReceipt(delivery_key=key, post_id=post_id))
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.get(ForumEmailReceipt, key)
        if existing:
            return {"ok": True, "duplicate": True, "post_id": existing.post_id}
        raise

    background_tasks.add_task(
        send_new_reply_notifications, category_id=topic.category_id,
        topic_id=topic_id, post_id=post_id, author_user_id=user_id,
        public_base_url=os.getenv("PUBLIC_BASE_URL", "https://tsk9sar.org"),
    )
    return {"ok": True, "duplicate": False, "post_id": post_id}


@router.post("/inbound-email")
async def inbound_email(request: Request, background_tasks: BackgroundTasks,
                        db: Session = Depends(get_db)):
    try:
        config = reply_config()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Email replies are not configured") from None
    if config is None:
        raise HTTPException(status_code=503, detail="Email replies are disabled")
    secret, webhook_secret, domain = config
    authorization = request.headers.get("authorization", "")
    if not hmac.compare_digest(authorization.encode(), f"Bearer {webhook_secret}".encode()):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "message/rfc822":
        raise HTTPException(status_code=415, detail="Expected message/rfc822")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_RAW_BYTES:
            raise HTTPException(status_code=413, detail="Email exceeds the 1 MB limit")
    return await run_in_threadpool(
        accept_reply, db, bytes(raw), request.headers.get("x-forum-envelope-from", ""),
        request.headers.get("x-forum-envelope-to", ""), secret, domain, background_tasks,
    )
