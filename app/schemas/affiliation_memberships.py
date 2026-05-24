from __future__ import annotations
from datetime import datetime
from typing import Optional, Literal, List
from pydantic import BaseModel, Field


class AffiliationMini(BaseModel):
    affiliation_id: int
    name: str


class HandlerAffiliationOut(BaseModel):
    affiliation: AffiliationMini
    started_at: datetime
    ended_at: Optional[datetime] = None
    note: Optional[str] = None


class HandlerAffiliationsResponse(BaseModel):
    current: List[HandlerAffiliationOut]
    past: List[HandlerAffiliationOut]


class AffiliationChangeRequestCreate(BaseModel):
    affiliation_id: int
    action: Literal["add", "remove"]
    note: Optional[str] = Field(default=None, max_length=2000)


class AffiliationChangeRequestOut(BaseModel):
    request_id: int
    handler_id: int
    handler_name: str

    affiliation: AffiliationMini
    action: Literal["add", "remove"]
    status: Literal["pending", "approved", "rejected"]

    requested_at: datetime
    request_note: Optional[str] = None

    reviewed_at: Optional[datetime] = None
    review_note: Optional[str] = None

class AffiliationChangeRequestOutHandler(BaseModel):
    request_id: int
    handler_id: int
    affiliation: AffiliationMini
    action: Literal["add", "remove"]
    status: Literal["pending", "approved", "rejected"]
    requested_at: datetime
    request_note: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_note: Optional[str] = None

    model_config = {"from_attributes": True}