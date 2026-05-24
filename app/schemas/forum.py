from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ForumCategoryOut(BaseModel):
    category_id: int
    name: str
    slug: str
    description: Optional[str] = None
    sortorder: int
    min_role: str
    notify_default: str

    topic_count: int = 0
    unread_count: int = 0
    last_topic_title: Optional[str] = None
    last_topic_id: Optional[int] = None
    last_post_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ForumTopicCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    body_md: str = Field(..., min_length=1)
    topic_type: str = "general"
    related_standard_id: Optional[int] = None

class SurveyCompletionOut(BaseModel):
    required_total: int = 0
    required_answered: int = 0
    required_missing: int = 0
    complete: bool = False

class ForumTopicSummaryOut(BaseModel):
    topic_id: int
    category_id: int
    title: str
    topic_type: str
    is_pinned: bool
    is_locked: bool
    last_post_at: datetime
    created_at: datetime
    created_by_user_id: int
    survey_completion: Optional[SurveyCompletionOut] = None
    survey_status: Optional[str] = None

    reply_count: int = 0
    is_unread: bool = False
    last_read_at: Optional[datetime] = None

    survey_completion: Optional[SurveyCompletionOut] = None

    class Config:
        from_attributes = True


class ForumPostCreate(BaseModel):
    body_md: str = Field(..., min_length=1)


class ForumPostOut(BaseModel):
    post_id: int
    topic_id: int
    body_md: str
    created_by_user_id: int

    author_name: Optional[str] = None
    sort_order: int | None = None
    edited_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ForumTopicDetailOut(BaseModel):
    topic_id: int
    category_id: int
    title: str
    topic_type: str
    related_standard_id: Optional[int] = None
    created_by_user_id: int
    is_pinned: bool
    is_locked: bool
    last_post_at: datetime
    created_at: datetime
    posts: List[ForumPostOut]

    class Config:
        from_attributes = True

class ForumActivitySummaryOut(BaseModel):
    unread_count: int = 0
    active_topic_count: int = 0

class ForumUserSettingsOut(BaseModel):
    email_mode: str = "category_default"

class ForumUserSettingsUpdate(BaseModel):
    email_mode: str

class ForumPostUpdate(BaseModel):
    body_md: str = Field(..., min_length=1)

class TopicLockIn(BaseModel):
    is_locked: bool

class BallotChoiceCreate(BaseModel):
    label: str
    allows_free_text: bool = False
    free_text_label: str | None = None


class BallotCreate(BaseModel):
    title: str
    description_md: str | None = None
    choices: list[BallotChoiceCreate]
    sort_order: int | None = None
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    is_required: bool = True
    max_choices_per_vote: int = 1
    show_results_before_vote: bool = True
    allow_vote_changes: bool = True
    show_live_results: bool = True

class BallotVoteCreate(BaseModel):
    choice_id: int | None = None
    choice_ids: list[int] | None = None


class BallotChoiceOut(BaseModel):
    choice_id: int
    label: str
    sort_order: int
    vote_count: int = 0
    allows_free_text: bool = False
    free_text_label: str | None = None
    user_feedback_text: str | None = None


class BallotOut(BaseModel):
    ballot_id: int
    topic_id: int
    post_id: int | None

    title: str
    description_md: str | None

    ballot_type: str

    is_required: bool = True
    user_has_answered: bool = False
    is_missing_required: bool = False

    status: str

    opens_at: datetime | None
    closes_at: datetime | None

    max_choices_per_vote: int

    show_results_before_vote: bool
    allow_vote_changes: bool
    show_live_results: bool

    user_choice_id: int | None
    user_choice_ids: list[int] = []

    created_by_user_id: int

    total_votes: int = 0

    choices: list[BallotChoiceOut] = []

    class Config:
        from_attributes = True
    
class BallotFeedbackIn(BaseModel):
    choice_id: int | None = None
    feedback_text: str


class BallotFeedbackOut(BaseModel):
    feedback_id: int
    ballot_id: int
    choice_id: int | None = None
    feedback_text: str
    created_at: datetime

    class Config:
        from_attributes = True

class BallotUpdate(BaseModel):
    title: str | None = None
    description_md: str | None = None
    choices: list[BallotChoiceCreate] | None = None
    sort_order: int | None = None
    max_choices_per_vote: int | None = None
    show_results_before_vote: bool | None = None
    allow_vote_changes: bool | None = None
    show_live_results: bool | None = None
    status: str | None = None
    is_required: bool | None = None

class CleanupConfirmIn(BaseModel):
    confirm_text: str
    expires_at: int
    confirm_hash: str
    