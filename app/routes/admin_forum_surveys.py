from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct

from app.database import get_db
from app.models.user import User
from app.utils.auth import get_current_user,require_admin
from app.models.forum import (
    ForumTopic,
    ForumBallot,
    ForumBallotChoice,
    ForumBallotVote,
    ForumBallotFeedback,
)

router = APIRouter(
    prefix="/admin/forum",
    tags=["Admin Forum Surveys"],
)


@router.get("/topics/{topic_id}/survey-report")
def get_topic_survey_report(
    topic_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    topic = db.query(ForumTopic).filter(ForumTopic.topic_id == topic_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    ballots = (
        db.query(ForumBallot)
        .filter(ForumBallot.topic_id == topic_id)
        .filter(ForumBallot.archived_at.is_(None))
        .order_by(ForumBallot.display_order.asc(), ForumBallot.ballot_id.asc())
        .all()
    )

    ballot_ids = [b.ballot_id for b in ballots]
    required_ids = [b.ballot_id for b in ballots if b.is_required]

    open_ballots = sum(1 for b in ballots if b.status == "open")
    closed_ballots = sum(1 for b in ballots if b.status == "closed")

    survey_status = (
        "closed"
        if ballots and open_ballots == 0
        else "open"
    )

    if not ballot_ids:
        return {
            "topic_id": topic.topic_id,
            "topic_title": topic.title,
            "total_ballots": 0,
            "required_ballots": 0,
            "participants": 0,
            "fully_completed": 0,
            "partial": 0,
            "ballots": [],
            "participants_detail": [],
        }

    vote_rows = (
        db.query(
            ForumBallotVote.user_id,
            ForumBallotVote.ballot_id,
        )
        .filter(ForumBallotVote.ballot_id.in_(ballot_ids))
        .group_by(ForumBallotVote.user_id, ForumBallotVote.ballot_id)
        .all()
    )

    by_user = {}
    for row in vote_rows:
        by_user.setdefault(row.user_id, set()).add(row.ballot_id)

    users = (
        db.query(User)
        .filter(User.user_id.in_(list(by_user.keys())))
        .all()
    )

    user_map = {
        u.user_id: f"{u.first_name or ''} {u.last_name or ''}".strip() or u.email
        for u in users
    }

    participants_detail = []
    fully_completed = 0
    partial = 0

    for user_id, answered in by_user.items():
        required_answered = len(set(required_ids).intersection(answered))
        is_complete = required_answered == len(required_ids) if required_ids else True

        if is_complete:
            fully_completed += 1
        else:
            partial += 1

        participants_detail.append({
            "user_id": user_id,
            "name": user_map.get(user_id, f"User {user_id}"),
            "answered_ballots": len(answered),
            "required_answered": required_answered,
            "required_total": len(required_ids),
            "complete": is_complete,
        })

    ballot_summaries = []

    for ballot in ballots:
        response_count = (
            db.query(func.count(distinct(ForumBallotVote.user_id)))
            .filter(ForumBallotVote.ballot_id == ballot.ballot_id)
            .scalar()
        )

        # In ballot_summaries.append(...)
        ballot_summaries.append({
            "ballot_id": ballot.ballot_id,

            "title": ballot.title,
            "is_required": ballot.is_required,
            "is_test": ballot.is_test,
            "is_open": ballot.status == "open",
            "status": ballot.status,
            "display_order": ballot.display_order,
            "responses": response_count or 0,
        })

    return {
        "topic_id": topic.topic_id,
        "topic_title": topic.title,
        "total_ballots": len(ballots),
        "required_ballots": len(required_ids),
        "participants": len(by_user),
        "fully_completed": fully_completed,
        "partial": partial,
        "ballots": ballot_summaries,
        "survey_status": survey_status,
        "open_ballots": open_ballots,
        "closed_ballots": closed_ballots,
        "participants_detail": sorted(
            participants_detail,
            key=lambda x: (not x["complete"], x["name"].lower()),
        ),
    }


@router.get("/ballots/{ballot_id}/report")
def get_ballot_report(
    ballot_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    ballot = db.query(ForumBallot).filter(ForumBallot.ballot_id == ballot_id).first()
    if not ballot:
        raise HTTPException(status_code=404, detail="Ballot not found")

    choices = (
        db.query(ForumBallotChoice)
        .filter(ForumBallotChoice.ballot_id == ballot_id)
        .order_by(ForumBallotChoice.sort_order.asc(), ForumBallotChoice.choice_id.asc())
        .all()
    )

    total_voters = (
        db.query(func.count(distinct(ForumBallotVote.user_id)))
        .filter(ForumBallotVote.ballot_id == ballot_id)
        .scalar()
    ) or 0

    choice_results = []

    for choice in choices:
        count = (
            db.query(func.count(ForumBallotVote.vote_id))
            .filter(ForumBallotVote.ballot_id == ballot_id)
            .filter(ForumBallotVote.choice_id == choice.choice_id)
            .scalar()
        ) or 0

        choice_results.append({
            "choice_id": choice.choice_id,
            "label": choice.label,
            "sort_order": choice.sort_order,
            "vote_count": count,
            "percent": round((count / total_voters) * 100, 1) if total_voters else 0,
        })

    feedback_rows = (
        db.query(ForumBallotFeedback, User)
        .join(User, User.user_id == ForumBallotFeedback.user_id)
        .filter(ForumBallotFeedback.ballot_id == ballot_id)
        .all()
    )

    freeform_responses = []
    blank_freeform = 0

    for feedback, user in feedback_rows:
        text = (feedback.feedback_text or "").strip()

        if not text:
            blank_freeform += 1
            continue

        freeform_responses.append({
            "feedback_id": feedback.feedback_id,
            "user_id": user.user_id,
            "name": f"{user.first_name or ''} {user.last_name or ''}".strip() or user.email,
            "text": text,
        })

    # In final return
    return {
        "ballot_id": ballot.ballot_id,
        "topic_id": ballot.topic_id,
        "title": ballot.title,
        "description_md": ballot.description_md,
        "is_required": ballot.is_required,
        "is_test": ballot.is_test,
        "status": ballot.status,
        "total_voters": total_voters,
        "choices": choice_results,
        "freeform": {
            "total_responses": len(freeform_responses),
            "blank_responses": blank_freeform,
            "responses": freeform_responses,
        },
    }

@router.get("/survey-topics")
def search_survey_topics(
    q: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):

    query = (
        db.query(ForumTopic)
        .join(ForumBallot, ForumBallot.topic_id == ForumTopic.topic_id)
        .filter(ForumBallot.archived_at.is_(None))
        .distinct()
    )

    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(ForumTopic.title.ilike(like))

    topics = (
        query
        .order_by(ForumTopic.updated_at.desc(), ForumTopic.topic_id.desc())
        .limit(25)
        .all()
    )

    return [
        {
            "topic_id": topic.topic_id,
            "title": topic.title,
        }
        for topic in topics
    ]

@router.post("/topics/{topic_id}/close-survey")
def close_topic_survey(
    topic_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):

    topic = db.query(ForumTopic).filter(ForumTopic.topic_id == topic_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    ballots = (
        db.query(ForumBallot)
        .filter(ForumBallot.topic_id == topic_id)
        .filter(ForumBallot.archived_at.is_(None))
        .all()
    )

    for ballot in ballots:
        ballot.status = "closed"

    db.commit()

    return {
        "topic_id": topic_id,
        "closed_ballots": len(ballots),
        "status": "closed",
    }

@router.post("/topics/{topic_id}/reopen-survey")
def reopen_topic_survey(
    topic_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):

    topic = db.query(ForumTopic).filter(ForumTopic.topic_id == topic_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    ballots = (
        db.query(ForumBallot)
        .filter(ForumBallot.topic_id == topic_id)
        .filter(ForumBallot.archived_at.is_(None))
        .all()
    )

    for ballot in ballots:
        ballot.status = "open"

    db.commit()

    return {
        "topic_id": topic_id,
        "opened_ballots": len(ballots),
        "status": "open",
    }