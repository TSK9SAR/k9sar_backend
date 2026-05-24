from pydantic import BaseModel, EmailStr, Field, HttpUrl
from typing import Optional

class AffiliationBase(BaseModel):
    name: str = Field(..., max_length=120)

    callout_line: Optional[str] = Field(None, max_length=255)
    contact_name: Optional[str] = Field(None, max_length=120)
    phone: Optional[str] = Field(None, max_length=50)
    location: Optional[str] = Field(None, max_length=120)
    url: Optional[str] = Field(None, max_length=255)

    sortorder: Optional[int] = None
    is_active: Optional[bool] = True

class AffiliationCreate(AffiliationBase):
    pass

class AffiliationUpdate(BaseModel):
    # all optional
    name: Optional[str] = Field(None, max_length=120)

    callout_line: Optional[str] = Field(None, max_length=255)
    contact_name: Optional[str] = Field(None, max_length=120)
    phone: Optional[str] = Field(None, max_length=50)
    location: Optional[str] = Field(None, max_length=120)
    url: Optional[str] = Field(None, max_length=255)

    sortorder: Optional[int] = None
    is_active: Optional[bool] = None

class AffiliationOut(AffiliationBase):
    affiliation_id: int

class AffiliationDetailOut(BaseModel):
    affiliation_id: int
    name: str
    callout_line: Optional[str] = None
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    location: Optional[str] = None
    url: Optional[str] = None
    sortorder: Optional[int] = None
    is_active: Optional[bool] = None

class AffiliationPublicOut(BaseModel):
    affiliation_id: int
    name: str
    callout_line: Optional[str] = None
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    url: Optional[str] = None
    sortorder: Optional[int] = None

    class Config:
        from_attributes = True


class AffiliationPublicDetailOut(AffiliationPublicOut):
    pass

class AffiliationMembershipOut(BaseModel):
    handler_id: Optional[int] = None
    user_id: Optional[int] = None

    first_name: Optional[str] = None
    last_name: Optional[str] = None

    phone: Optional[str] = None
    email: Optional[str] = None

    role: Optional[str] = None
    evaluator: Optional[str] = None

    address_line1: Optional[str] = None
    city: Optional[str] = None

class Config:
    from_attributes = True