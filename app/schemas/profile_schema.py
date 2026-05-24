# app/schemas/profile_schema.py
from typing import Optional
from pydantic import BaseModel, EmailStr, Field

class HandlerFields(BaseModel):
    experience_level: Optional[str] = None
    status: Optional[str] = None
    group_affiliation: Optional[str] = None
    notes: Optional[str] = None

class ProfileOut(BaseModel):
    # user
    user_id: int
    first_name: str
    last_name: str
    email: EmailStr
    phone: Optional[str] = None

    domicile_lat: Optional[float] = None
    domicile_lng: Optional[float] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state_province: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None

    # handler (flattened)
    has_handler: bool = False
    handler_id: Optional[int] = None
    handler: HandlerFields = Field(default_factory=HandlerFields)
    
class ProfileUpdate(BaseModel):
    # user fields
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    domicile_lat: Optional[float] = None
    domicile_lng: Optional[float] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state_province: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None

    # accept nested handler updates too
    handler: Optional[HandlerFields] = None
