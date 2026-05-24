from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.database import get_db

from app.schemas.forum import (
    ForumCategoryOut,
    ForumPostCreate,
    ForumPostOut,
    ForumTopicCreate,
    ForumTopicDetailOut,
    ForumTopicSummaryOut,
    ForumActivitySummaryOut,
    ForumUserSettingsOut,
    ForumUserSettingsUpdate,
    ForumPostUpdate,
    TopicLockIn,
    BallotCreate,
    BallotOut,
    BallotVoteCreate,
    BallotFeedbackIn,
    BallotFeedbackOut,
    BallotUpdate,
    SurveyCompletionOut,
)

from app.models.forum import (
    ForumCategory,
    ForumPost,
    ForumTopic,
    ForumTopicRead,
    ForumUserSetting,
    ForumBallot,
    ForumBallotChoice,
    ForumBallotVote,
    ForumBallotFeedback,
)

from app.utils.auth import get_current_user

import os

from app.services.forum_notifications import (
    send_new_topic_notifications,
    send_new_reply_notifications,
)
from app.utils.auth import require_admin

router = APIRouter(prefix="/api/forums", tags=["Forum"])


def _user_roles(user) -> set[str]:
    return {r.role_name for r in getattr(user, "roles", [])}


def _is_admin(user) -> bool:
    return "admin" in _user_roles(user)


def _has_forum_access(user, category: ForumCategory) -> bool:
    roles = _user_roles(user)

    if "admin" in roles:
        return True

    required = category.min_role

    if required == "member":
        return True

    if required == "evaluator":
        return "evaluator" in roles or "supervisor" in roles

    if required == "supervisor":
        return "supervisor" in roles

    if required == "admin":
        return False

    return False

def _next_sort_order(db: Session, topic_id: int) -> int:
    max_sort = (
        db.query(func.max(ForumPost.sort_order))
        .filter(ForumPost.topic_id == topic_id)
        .scalar()
    )

    return int(max_sort or 0) + 10


def _require_category_access(user, category: ForumCategory):
    if not category or not category.is_active:
        raise HTTPException(status_code=404, detail="Forum category not found")

    if not _has_forum_access(user, category):
        raise HTTPException(status_code=403, detail="Not allowed to access this forum")


@router.get("/", response_model=list[ForumCategoryOut])
def list_forums(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    categories = (
        db.query(ForumCategory)
        .filter(ForumCategory.is_active == True)
        .order_by(ForumCategory.sortorder, ForumCategory.name)
        .all()
    )

    result = []

    for category in categories:
        if not _has_forum_access(current_user, category):
            continue

        topics = (
            db.query(ForumTopic)
            .filter(ForumTopic.category_id == category.category_id)
            .order_by(ForumTopic.last_post_at.desc())
            .all()
        )

        unread_count = 0

        for topic in topics:
            read_row = (
                db.query(ForumTopicRead)
                .filter(
                    ForumTopicRead.user_id == current_user.user_id,
                    ForumTopicRead.topic_id == topic.topic_id,
                )
                .first()
            )

            if read_row is None or topic.last_post_at > read_row.last_read_at:
                unread_count += 1

        last_topic = topics[0] if topics else None

        result.append(
            ForumCategoryOut(
                category_id=category.category_id,
                name=category.name,
                slug=category.slug,
                description=category.description,
                sortorder=category.sortorder,
                min_role=category.min_role,
                notify_default=category.notify_default,
                topic_count=len(topics),
                unread_count=unread_count,
                last_topic_title=last_topic.title if last_topic else None,
                last_topic_id=last_topic.topic_id if last_topic else None,
                last_post_at=last_topic.last_post_at if last_topic else None,
            )
        )

    return result


def ballot_is_open(ballot: ForumBallot) -> bool:
    now = datetime.utcnow()

    if ballot.status != "open":
        return False

    if ballot.opens_at and now < ballot.opens_at:
        return False

    if ballot.closes_at and now > ballot.closes_at:
        return False

    return True

@router.get("/activity/summary", response_model=ForumActivitySummaryOut)
def forum_activity_summary(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    categories = (
        db.query(ForumCategory)
        .filter(ForumCategory.is_active == True)
        .all()
    )

    unread_count = 0
    active_topic_count = 0

    for category in categories:
        if not _has_forum_access(current_user, category):
            continue

        topics = (
            db.query(ForumTopic)
            .filter(ForumTopic.category_id == category.category_id)
            .all()
        )

        active_topic_count += len(topics)

        for topic in topics:
            read_row = (
                db.query(ForumTopicRead)
                .filter(
                    ForumTopicRead.user_id == current_user.user_id,
                    ForumTopicRead.topic_id == topic.topic_id,
                )
                .first()
            )

            if read_row is None or topic.last_post_at > read_row.last_read_at:
                unread_count += 1

    return ForumActivitySummaryOut(
        unread_count=unread_count,
        active_topic_count=active_topic_count,
    )

@router.get("/{category_id}/topics", response_model=list[ForumTopicSummaryOut])
def list_topics(
    category_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    category = db.query(ForumCategory).filter(
        ForumCategory.category_id == category_id
    ).first()

    _require_category_access(current_user, category)

    rows = (
        db.query(
            ForumTopic,
            func.count(ForumPost.post_id).label("post_count"),
            ForumTopicRead.last_read_at.label("last_read_at"),
        )
        .outerjoin(
            ForumPost,
            (ForumPost.topic_id == ForumTopic.topic_id)
            & (ForumPost.deleted_at.is_(None)),
        )
        .outerjoin(
            ForumTopicRead,
            and_(
                ForumTopicRead.topic_id == ForumTopic.topic_id,
                ForumTopicRead.user_id == current_user.user_id,
            ),
        )
        .filter(ForumTopic.category_id == category_id)
        .group_by(ForumTopic.topic_id, ForumTopicRead.last_read_at)
        .order_by(ForumTopic.is_pinned.desc(), ForumTopic.last_post_at.desc())
        .all()
    )

    result = []

    for topic, post_count, last_read_at in rows:
        item = ForumTopicSummaryOut.model_validate(topic)

        item.reply_count = max(int(post_count or 0) - 1, 0)
        item.last_read_at = last_read_at
        item.is_unread = (
            last_read_at is None
            or topic.last_post_at > last_read_at
        )

        required_ballot_ids = [
            ballot_id
            for (ballot_id,) in (
                db.query(ForumBallot.ballot_id)
                .filter(ForumBallot.topic_id == topic.topic_id)
                .filter(ForumBallot.is_required.is_(True))
                .filter(ForumBallot.archived_at.is_(None))
                .all()
            )
        ]

        required_total = len(required_ballot_ids)

        if required_total:
            required_answered = (
                db.query(func.count(func.distinct(ForumBallotVote.ballot_id)))
                .filter(ForumBallotVote.user_id == current_user.user_id)
                .filter(ForumBallotVote.ballot_id.in_(required_ballot_ids))
                .scalar()
            ) or 0

            required_missing = required_total - int(required_answered)

            item.survey_completion = SurveyCompletionOut(
                required_total=required_total,
                required_answered=int(required_answered),
                required_missing=required_missing,
                complete=required_missing == 0,
            )
        else:
            item.survey_completion = None

        ballot_status_rows = (
            db.query(ForumBallot.status)
            .filter(ForumBallot.topic_id == topic.topic_id)
            .filter(ForumBallot.archived_at.is_(None))
            .all()
        )

        ballot_statuses = [
            (row[0] or "").lower()
            for row in ballot_status_rows
        ]

        if ballot_statuses:
            item.survey_status = (
                "closed"
                if all(status == "closed" for status in ballot_statuses)
                else "open"
            )
        else:
            item.survey_status = None

        result.append(item)

    return result

@router.get("/me/settings", response_model=ForumUserSettingsOut)
def get_my_forum_settings(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    setting = (
        db.query(ForumUserSetting)
        .filter(ForumUserSetting.user_id == current_user.user_id)
        .first()
    )

    if not setting:
        return ForumUserSettingsOut(email_mode="category_default")

    return ForumUserSettingsOut(
        email_mode=setting.email_mode
    )


@router.patch("/me/settings", response_model=ForumUserSettingsOut)
def update_my_forum_settings(
    payload: ForumUserSettingsUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    allowed = {
        "category_default",
        "all",
        "announcements",
        "none",
    }

    if payload.email_mode not in allowed:
        raise HTTPException(
            status_code=400,
            detail="Invalid email mode",
        )

    setting = (
        db.query(ForumUserSetting)
        .filter(ForumUserSetting.user_id == current_user.user_id)
        .first()
    )

    if not setting:
        setting = ForumUserSetting(
            user_id=current_user.user_id,
            email_mode=payload.email_mode,
        )
        db.add(setting)
    else:
        setting.email_mode = payload.email_mode

    db.commit()

    return ForumUserSettingsOut(
        email_mode=setting.email_mode
    )

@router.post("/{category_id}/topics", response_model=ForumTopicDetailOut, status_code=status.HTTP_201_CREATED)
def create_topic(
    category_id: int,
    payload: ForumTopicCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    category = db.query(ForumCategory).filter(ForumCategory.category_id == category_id).first()
    _require_category_access(current_user, category)

    topic = ForumTopic(
        category_id=category_id,
        title=payload.title.strip(),
        topic_type=payload.topic_type,
        related_standard_id=payload.related_standard_id,
        created_by_user_id=current_user.user_id,
        last_post_at=datetime.utcnow(),
    )

    db.add(topic)
    db.flush()

    post = ForumPost(
        topic_id=topic.topic_id,
        body_md=payload.body_md.strip(),
        created_by_user_id=current_user.user_id,
    )

    db.add(post)
    db.commit()
    db.refresh(topic)

    public_base_url = os.getenv("PUBLIC_BASE_URL", "https://tsk9sar.org")
    
    background_tasks.add_task(
        send_new_topic_notifications,
        category_id=category.category_id,
        topic_id=topic.topic_id,
        post_id=post.post_id,
        author_user_id=current_user.user_id,
        public_base_url=public_base_url,
    )

    return topic


@router.get("/topics/{topic_id}", response_model=ForumTopicDetailOut)
def get_topic(
    topic_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    topic = db.query(ForumTopic).filter(ForumTopic.topic_id == topic_id).first()

    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    _require_category_access(current_user, topic.category)

    topic.posts = [p for p in topic.posts if p.deleted_at is None]

    read_row = (
        db.query(ForumTopicRead)
        .filter(
            ForumTopicRead.user_id == current_user.user_id,
            ForumTopicRead.topic_id == topic.topic_id,
        )
        .first()
    )

    if read_row:
        read_row.last_read_at = datetime.utcnow()
    else:
        db.add(
            ForumTopicRead(
                user_id=current_user.user_id,
                topic_id=topic.topic_id,
                last_read_at=datetime.utcnow(),
            )
        )

    db.commit()

    visible_posts = [p for p in topic.posts if p.deleted_at is None]

    posts_out = []

    for p in visible_posts:
        user = p.created_by
        author_name = None

        if user:
            first = getattr(user, "first_name", "") or ""
            last = getattr(user, "last_name", "") or ""
            author_name = f"{first} {last}".strip() or getattr(user, "email", None)

        posts_out.append(
            ForumPostOut(
                post_id=p.post_id,
                topic_id=p.topic_id,
                body_md=p.body_md,
                created_by_user_id=p.created_by_user_id,
                author_name=author_name,
                edited_at=p.edited_at,
                deleted_at=p.deleted_at,
                created_at=p.created_at,
                sort_order=p.sort_order,
                post_type=p.post_type,
            )
        )

    return ForumTopicDetailOut(
        topic_id=topic.topic_id,
        category_id=topic.category_id,
        title=topic.title,
        topic_type=topic.topic_type,
        related_standard_id=topic.related_standard_id,
        created_by_user_id=topic.created_by_user_id,
        is_pinned=topic.is_pinned,
        is_locked=topic.is_locked,
        last_post_at=topic.last_post_at,
        created_at=topic.created_at,
        posts=posts_out,
    )


def _ballot_out(db: Session, ballot: ForumBallot, current_user) -> BallotOut:
    vote_counts = dict(
        db.query(
            ForumBallotVote.choice_id,
            func.count(ForumBallotVote.vote_id),
        )
        .filter(ForumBallotVote.ballot_id == ballot.ballot_id)
        .group_by(ForumBallotVote.choice_id)
        .all()
    )

    user_votes = (
        db.query(ForumBallotVote)
        .filter(
            ForumBallotVote.ballot_id == ballot.ballot_id,
            ForumBallotVote.user_id == current_user.user_id,
        )
        .all()
    )

    feedback_rows = (
        db.query(ForumBallotFeedback)
        .filter(
            ForumBallotFeedback.ballot_id == ballot.ballot_id,
            ForumBallotFeedback.user_id == current_user.user_id,
        )
        .all()
    )

    feedback_by_choice_id = {
        f.choice_id: f.feedback_text
        for f in feedback_rows
    }

    user_choice_ids = [v.choice_id for v in user_votes]
    user_choice_id = user_choice_ids[0] if user_choice_ids else None
    user_has_answered = len(user_votes) > 0

    total_votes = sum(int(v or 0) for v in vote_counts.values())

    return BallotOut(
        ballot_id=ballot.ballot_id,
        topic_id=ballot.topic_id,
        post_id=ballot.post_id,
        title=ballot.title,
        description_md=ballot.description_md,
        ballot_type=ballot.ballot_type,
        is_required=ballot.is_required,
        user_has_answered=user_has_answered,
        is_missing_required=ballot.is_required and not user_has_answered,
        status=ballot.status,
        opens_at=ballot.opens_at,
        closes_at=ballot.closes_at,
        max_choices_per_vote=ballot.max_choices_per_vote,
        show_results_before_vote=ballot.show_results_before_vote,
        allow_vote_changes=ballot.allow_vote_changes,
        show_live_results=ballot.show_live_results,
        user_choice_id=user_choice_id,
        created_by_user_id=ballot.created_by_user_id,
        user_choice_ids=user_choice_ids,
        total_votes=total_votes,
        choices=[
            {
                "choice_id": c.choice_id,
                "label": c.label,
                "sort_order": c.sort_order,
                "vote_count": int(vote_counts.get(c.choice_id, 0)),
                "allows_free_text": c.allows_free_text,
                "free_text_label": c.free_text_label,
                "user_feedback_text": feedback_by_choice_id.get(c.choice_id),
            }
            for c in ballot.choices
        ],
    )


@router.get("/topics/{topic_id}/ballots", response_model=list[BallotOut])
def get_topic_ballots(
    topic_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    topic = (
        db.query(ForumTopic)
        .filter(ForumTopic.topic_id == topic_id)
        .first()
    )

    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    _require_category_access(current_user, topic.category)

    ballots = (
        db.query(ForumBallot)
        .filter(ForumBallot.topic_id == topic_id)
        .join(ForumPost, ForumBallot.post_id == ForumPost.post_id)
        .order_by(
            func.coalesce(ForumPost.sort_order, ForumPost.post_id).asc(),
            ForumPost.post_id.asc(),
        )
    )

    return [
        _ballot_out(db, ballot, current_user)
        for ballot in ballots
    ]


@router.post(
    "/posts/{post_id}/ballot",
    response_model=BallotOut,
    status_code=status.HTTP_201_CREATED,
)
def create_post_ballot(
    post_id: int,
    payload: BallotCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    roles = _user_roles(current_user)
    is_admin = "admin" in roles
    is_supervisor = "supervisor" in roles

    if not is_admin and not is_supervisor:
        raise HTTPException(status_code=403, detail="Not allowed to create polls")

    post = (
        db.query(ForumPost)
        .filter(ForumPost.post_id == post_id)
        .first()
    )

    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    if post.created_by_user_id != current_user.user_id:
        raise HTTPException(
            status_code=403,
            detail="You may only create polls on your own posts.",
        )

    topic = post.topic

    _require_category_access(current_user, topic.category)

    existing = (
        db.query(ForumBallot)
        .filter(ForumBallot.post_id == post_id)
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=400,
            detail="This post already has a ballot.",
        )

    clean_choices = [
        c
        for c in payload.choices
        if c.label and c.label.strip()
    ]

    has_free_text_choice = any(c.allows_free_text for c in clean_choices)

    if len(clean_choices) < 2 and not has_free_text_choice:
        raise HTTPException(
            status_code=400,
            detail="A ballot needs at least two choices unless it is a free-form question.",
        )

    ballot = ForumBallot(
        topic_id=topic.topic_id,
        post_id=post.post_id,
        created_by_user_id=current_user.user_id,
        title=payload.title.strip(),
        description_md=payload.description_md,
        ballot_type="poll",
        opens_at=payload.opens_at,
        closes_at=payload.closes_at,
        is_required=payload.is_required,
        max_choices_per_vote=payload.max_choices_per_vote,
        show_results_before_vote=payload.show_results_before_vote,
        allow_vote_changes=payload.allow_vote_changes,
        show_live_results=payload.show_live_results,

        status="open",
    )

    db.add(ballot)
    db.flush()

    for index, choice in enumerate(clean_choices):
        db.add(
            ForumBallotChoice(
                ballot_id=ballot.ballot_id,
                label=choice.label.strip(),
                sort_order=index,
                allows_free_text=choice.allows_free_text,
                free_text_label=choice.free_text_label,
            )
        )

    db.commit()
    db.refresh(ballot)

    return _ballot_out(db, ballot, current_user)

@router.post("/ballots/{ballot_id}/vote", response_model=BallotOut)
def vote_ballot(
    ballot_id: int,
    payload: BallotVoteCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    ballot = (
        db.query(ForumBallot)
        .filter(ForumBallot.ballot_id == ballot_id)
        .first()
    )

    if not ballot:
        raise HTTPException(status_code=404, detail="Ballot not found")

    topic = db.query(ForumTopic).filter(ForumTopic.topic_id == ballot.topic_id).first()

    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    _require_category_access(current_user, topic.category)

    if not ballot_is_open(ballot):
        raise HTTPException(status_code=400, detail="This ballot is not open.")

    existing_votes = (
        db.query(ForumBallotVote)
        .filter(
            ForumBallotVote.ballot_id == ballot.ballot_id,
            ForumBallotVote.user_id == current_user.user_id,
        )
        .all()
    )

    if existing_votes and not ballot.allow_vote_changes:
        raise HTTPException(status_code=400, detail="You have already voted.")

    if payload.choice_ids is not None:
        requested_choice_ids = payload.choice_ids
    elif payload.choice_id is not None:
        requested_choice_ids = [payload.choice_id]
    else:
        raise HTTPException(status_code=400, detail="No choices selected.")

    requested_choice_ids = list(dict.fromkeys(int(x) for x in requested_choice_ids))

    if not requested_choice_ids:
        raise HTTPException(status_code=400, detail="No choices selected.")

    max_choices = ballot.max_choices_per_vote or 1

    if len(requested_choice_ids) > max_choices:
        raise HTTPException(
            status_code=400,
            detail=f"You may select up to {max_choices} choices.",
        )

    valid_choice_ids = {
        c.choice_id
        for c in db.query(ForumBallotChoice)
        .filter(ForumBallotChoice.ballot_id == ballot.ballot_id)
        .all()
    }

    invalid = [cid for cid in requested_choice_ids if cid not in valid_choice_ids]

    if invalid:
        raise HTTPException(status_code=400, detail="Invalid choice for this ballot.")

    db.query(ForumBallotVote).filter(
        ForumBallotVote.ballot_id == ballot.ballot_id,
        ForumBallotVote.user_id == current_user.user_id,
    ).delete(synchronize_session=False)

    now = datetime.utcnow()

    for choice_id in requested_choice_ids:
        db.add(
            ForumBallotVote(
                ballot_id=ballot.ballot_id,
                choice_id=choice_id,
                user_id=current_user.user_id,
                voted_at=now,
            )
        )

    db.commit()
    db.refresh(ballot)

    return _ballot_out(db, ballot, current_user)

@router.post("/topics/{topic_id}/posts", response_model=ForumPostOut, status_code=status.HTTP_201_CREATED)
def create_reply(
    topic_id: int,
    payload: ForumPostCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    topic = db.query(ForumTopic).filter(ForumTopic.topic_id == topic_id).first()

    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    _require_category_access(current_user, topic.category)

    if topic.is_locked and not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="Topic is locked")

    next_sort = _next_sort_order(db, topic.topic_id)

    post = ForumPost(
        topic_id=topic.topic_id,
        body_md=payload.body_md.strip(),
        sort_order=next_sort,
        created_by_user_id=current_user.user_id,
    )

    topic.last_post_at = datetime.utcnow()

    db.add(post)
    db.commit()
    db.refresh(post)

    public_base_url = os.getenv("PUBLIC_BASE_URL", "https://tsk9sar.org")

    background_tasks.add_task(
        send_new_reply_notifications,
        category_id=topic.category_id,
        topic_id=topic.topic_id,
        post_id=post.post_id,
        author_user_id=current_user.user_id,
        public_base_url=public_base_url,
    )

    return post

@router.patch("/posts/{post_id}", response_model=ForumPostOut)
def update_post(
    post_id: int,
    payload: ForumPostUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    post = (
        db.query(ForumPost)
        .filter(ForumPost.post_id == post_id)
        .first()
    )

    if not post or post.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Post not found")

    topic = post.topic
    _require_category_access(current_user, topic.category)

    is_author = post.created_by_user_id == current_user.user_id
    is_admin = _is_admin(current_user)

    if not is_author and not is_admin:
        raise HTTPException(status_code=403, detail="Not allowed to edit this post")

    if topic.is_locked and not is_admin:
        raise HTTPException(status_code=403, detail="Topic is locked")

    post.body_md = payload.body_md.strip()
    post.edited_at = datetime.utcnow()

    db.commit()
    db.refresh(post)

    author_name = None
    user = post.created_by
    if user:
        first = getattr(user, "first_name", "") or ""
        last = getattr(user, "last_name", "") or ""
        author_name = f"{first} {last}".strip() or getattr(user, "email", None)

    return ForumPostOut(
        post_id=post.post_id,
        topic_id=post.topic_id,
        body_md=post.body_md,
        created_by_user_id=post.created_by_user_id,
        author_name=author_name,
        edited_at=post.edited_at,
        deleted_at=post.deleted_at,
        created_at=post.created_at,
    )

@router.patch("/topics/{topic_id}/lock")
def update_topic_lock(
    topic_id: int,
    payload: TopicLockIn,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):

    topic = db.get(ForumTopic, topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    topic.is_locked = payload.is_locked
    db.commit()
    return {"ok": True, "is_locked": topic.is_locked}

@router.delete("/posts/{post_id}")
def delete_post(
    post_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    post = (
        db.query(ForumPost)
        .filter(ForumPost.post_id == post_id)
        .first()
    )

    if not post or post.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Post not found")

    topic = post.topic
    _require_category_access(current_user, topic.category)

    is_author = post.created_by_user_id == current_user.user_id
    is_admin = _is_admin(current_user)

    if not is_author and not is_admin:
        raise HTTPException(status_code=403, detail="Not allowed to delete this post")

    if topic.is_locked and not is_admin:
        raise HTTPException(status_code=403, detail="Topic is locked")

    # Safer than hard delete: preserves thread and poll/vote history.
    post.deleted_at = datetime.utcnow()
    post.edited_at = datetime.utcnow()

    db.commit()

    return {"ok": True}

@router.post("/ballots/{ballot_id}/feedback", response_model=BallotFeedbackOut)
def save_ballot_feedback(
    ballot_id: int,
    payload: BallotFeedbackIn,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    ballot = db.query(ForumBallot).filter(
        ForumBallot.ballot_id == ballot_id
    ).first()

    if not ballot:
        raise HTTPException(status_code=404, detail="Ballot not found")

    topic = db.query(ForumTopic).filter(
        ForumTopic.topic_id == ballot.topic_id
    ).first()

    _require_category_access(current_user, topic.category)

    text = (payload.feedback_text or "").strip()

    if not text:
        raise HTTPException(status_code=400, detail="Feedback text is required.")

    feedback = (
        db.query(ForumBallotFeedback)
        .filter(
            ForumBallotFeedback.ballot_id == ballot_id,
            ForumBallotFeedback.user_id == current_user.user_id,
            ForumBallotFeedback.choice_id == payload.choice_id,
        )
        .first()
    )

    if feedback:
        feedback.feedback_text = text
        feedback.updated_at = datetime.utcnow()
    else:
        feedback = ForumBallotFeedback(
            ballot_id=ballot_id,
            user_id=current_user.user_id,
            choice_id=payload.choice_id,
            feedback_text=text,
        )
        db.add(feedback)

    db.commit()
    db.refresh(feedback)

    return feedback

@router.patch("/ballots/{ballot_id}", response_model=BallotOut)
def update_ballot(
    ballot_id: int,
    payload: BallotUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    ballot = (
        db.query(ForumBallot)
        .filter(ForumBallot.ballot_id == ballot_id)
        .first()
    )

    if not ballot:
        raise HTTPException(status_code=404, detail="Ballot not found")

    topic = (
        db.query(ForumTopic)
        .filter(ForumTopic.topic_id == ballot.topic_id)
        .first()
    )

    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    _require_category_access(current_user, topic.category)

    roles = _user_roles(current_user)
    is_admin = "admin" in roles
    is_author = ballot.created_by_user_id == current_user.user_id

    if not is_admin and not is_author:
        raise HTTPException(status_code=403, detail="Not allowed to edit this poll")

    vote_count = (
        db.query(ForumBallotVote)
        .filter(ForumBallotVote.ballot_id == ballot.ballot_id)
        .count()
    )

    if payload.title is not None:
        title = payload.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="Poll title is required")
        ballot.title = title

    if payload.description_md is not None:
        ballot.description_md = payload.description_md.strip()

    if payload.max_choices_per_vote is not None:
        ballot.max_choices_per_vote = max(1, int(payload.max_choices_per_vote))

    if payload.show_results_before_vote is not None:
        ballot.show_results_before_vote = payload.show_results_before_vote

    if payload.allow_vote_changes is not None:
        ballot.allow_vote_changes = payload.allow_vote_changes

    if payload.show_live_results is not None:
        ballot.show_live_results = payload.show_live_results

    if payload.is_required is not None:
        ballot.is_required = payload.is_required

    if payload.status is not None:
        if payload.status not in {"open", "closed", "archived"}:
            raise HTTPException(status_code=400, detail="Invalid poll status")
        ballot.status = payload.status

    if payload.choices is not None:
        if vote_count > 0:
            raise HTTPException(
                status_code=400,
                detail="Choices cannot be changed after voting has started.",
            )

        clean_choices = [
            c for c in payload.choices
            if c.label and c.label.strip()
        ]

        has_free_text_choice = any(c.allows_free_text for c in clean_choices)

        if len(clean_choices) < 2 and not has_free_text_choice:
            raise HTTPException(
                status_code=400,
                detail="A ballot needs at least two choices unless it is a free-form question.",
            )

        db.query(ForumBallotChoice).filter(
            ForumBallotChoice.ballot_id == ballot.ballot_id
        ).delete(synchronize_session=False)

        for index, choice in enumerate(clean_choices):
            db.add(
                ForumBallotChoice(
                    ballot_id=ballot.ballot_id,
                    label=choice.label.strip(),
                    sort_order=index,
                    allows_free_text=choice.allows_free_text,
                    free_text_label=choice.free_text_label,
                )
            )
        if payload.sort_order is not None:
            post = (
                db.query(ForumPost)
                .filter(ForumPost.post_id == ballot.post_id)
                .first()
            )

            if post:
                post.sort_order = payload.sort_order

    db.commit()
    db.refresh(ballot)

    return _ballot_out(db, ballot, current_user)

@router.post(
    "/topics/{topic_id}/poll-question",
    response_model=BallotOut,
    status_code=status.HTTP_201_CREATED,
)
def create_topic_poll_question(
    topic_id: int,
    payload: BallotCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    roles = _user_roles(current_user)

    if "admin" not in roles and "supervisor" not in roles:
        raise HTTPException(status_code=403, detail="Not allowed to create polls")

    topic = db.query(ForumTopic).filter(ForumTopic.topic_id == topic_id).first()

    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    _require_category_access(current_user, topic.category)

    next_sort = _next_sort_order(db, topic.topic_id)

    post = ForumPost(
        topic_id=topic.topic_id,
        body_md="",
        post_type="poll",
        sort_order=payload.sort_order or next_sort,
        created_by_user_id=current_user.user_id,
    )

    topic.last_post_at = datetime.utcnow()

    db.add(post)
    db.flush()

    clean_choices = [
        c
        for c in payload.choices
        if c.label and c.label.strip()
    ]

    has_free_text_choice = any(c.allows_free_text for c in clean_choices)

    if len(clean_choices) < 2 and not has_free_text_choice:
        raise HTTPException(
            status_code=400,
            detail="A ballot needs at least two choices unless it is a free-form question.",
        )

    ballot = ForumBallot(
        topic_id=topic.topic_id,
        post_id=post.post_id,
        created_by_user_id=current_user.user_id,
        title=payload.title.strip(),
        description_md=payload.description_md,
        ballot_type="poll",
        max_choices_per_vote=payload.max_choices_per_vote,
        show_results_before_vote=payload.show_results_before_vote,
        allow_vote_changes=payload.allow_vote_changes,
        show_live_results=payload.show_live_results,
        status="open",
    )

    db.add(ballot)
    db.flush()

    for index, choice in enumerate(clean_choices):
        db.add(
            ForumBallotChoice(
                ballot_id=ballot.ballot_id,
                label=choice.label.strip(),
                sort_order=index,
                allows_free_text=choice.allows_free_text,
                free_text_label=choice.free_text_label,
            )
        )

    db.commit()
    db.refresh(ballot)

    return _ballot_out(db, ballot, current_user)

    