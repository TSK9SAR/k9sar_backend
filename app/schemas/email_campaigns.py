# app/schemas/email_campaigns.py

from typing import Optional, List
from pydantic import BaseModel


class EmailAudienceFilters(BaseModel):
    q: str | None = None
    user_ids: list[int] = []
    discipline_group_id: int | None = None
    discipline_id: int | None = None
    certification_status: str | None = None
    affiliation_id: int | None = None
    expiring_within_days: int | None = None
    active_handlers_only: bool = True
    user_type: str | None = None
    special_rule: str | None = None

class EmailAudiencePreviewRequest(BaseModel):
    filters: EmailAudienceFilters
    excluded_user_ids: List[int] = []


class EmailAudienceRecipientOut(BaseModel):
    user_id: int
    name: str
    email: str
    affiliation: Optional[str] = None
    is_evaluator: bool = False


class EmailAudiencePreviewOut(BaseModel):
    total: int
    recipients: List[EmailAudienceRecipientOut]

class EmailAudienceSendRequest(BaseModel):
    filters: EmailAudienceFilters
    excluded_user_ids: list[int] = []
    subject: str
    body_text: str
    enable_reply: bool = False


class EmailAudienceSendOut(BaseModel):
    campaign_id: int
    recipient_count: int
    sent_count: int
    failed_count: int
    status: str