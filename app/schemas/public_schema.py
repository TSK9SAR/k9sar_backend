# app/schemas/public_schema.py
from pydantic import BaseModel, EmailStr
from typing import List, Optional
from datetime import datetime

class PublicActiveCert(BaseModel):
    discipline: str
    expires_mm_yy: str  # "MM/YY"

class PublicTeamRow(BaseModel):
    team_id: int
    handler_full_name: str
    email: EmailStr
    phone: Optional[str] = None
    dog_name: str
    distance_mi: Optional[float] = None
    distance_km: Optional[float] = None
    active_certs: List[PublicActiveCert]

class PublicMatrixResponse(BaseModel):
    disciplines: List[str]
    teams: List[PublicTeamRow]

class PublicStandardOut(BaseModel):
    standard_id: int
    name: str
    description: Optional[str] = None
    replacement_date: Optional[str] = None
    certification_id: Optional[int] = None

class PublicAffiliationOut(BaseModel):
    affiliation_id: int
    name: str
    callout_line: Optional[str] = None
    sortorder: Optional[int] = None

class AffiliationPublicOut(BaseModel):
    affiliation_id: int
    name: str

    callout_line: Optional[str] = None
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    url: Optional[str] = None

    sortorder: Optional[int] = None

    model_config = {"from_attributes": True}

class PublicPortalTrackIn(BaseModel):
    section: str
    session_id: str | None = None 

class PublicPortalEventOut(BaseModel):
    event_id: int
    occurred_at: datetime
    section: str
    session_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    referer: str | None = None

    class Config:
        from_attributes = True