# app/schemas/handler_schema.py
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, date
from typing import Literal
from app.schemas.user_schema import UserOut  # ✅ import user schema

class HandlerBase(BaseModel):
    experience_level: Optional[str] = None
    status: Optional[str] = "active"
    group_affiliation: Optional[str] = None
    notes: Optional[str] = None

class HandlerCreate(HandlerBase):
    user_id: int  # must reference an existing user

class HandlerUpdate(HandlerBase):
    pass

class HandlerOut(HandlerBase):
    handler_id: int
    user: UserOut
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class HandlerEnsureOut(BaseModel):
    handler_id: int
    created: bool = False

class Config:
    orm_mode = True

class HandlerDuesOut(BaseModel):
    handler_id: int
    dues_year: int
    status: str
    amount_due: float
    amount_paid: float | None = None
    paid_on: date | None = None
    payment_method: str | None = None
    reference_note: str | None = None


    class Config:
        from_attributes = True


class HandlerDuesUpsertIn(BaseModel):
    dues_year: int
    status: Literal["unpaid", "paid", "waived"]

    amount_paid: float | None = None
    paid_on: date | None = None
    payment_method: str | None = None
    reference_note: str | None = None


    class Config:
        from_attributes = True


class HandlerDuesRosterRow(BaseModel):
    handler_id: int
    handler_name: str
    email: str | None = None
    dues_year: int
    status: str
    amount_due: float
    amount_paid: float | None = None
    paid_on: date | None = None
    payment_method: str | None = None
    reference_note: str | None = None


    class Config:
        from_attributes = True
