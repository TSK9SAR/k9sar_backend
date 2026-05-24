from datetime import date, datetime
from typing import Optional, Any
from pydantic import BaseModel, field_validator

def parse_date_flexible(v: Any) -> Optional[date]:
    if v is None or v == "":
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()

    s = str(v).strip()

    # Accept ISO first (fast path)
    try:
        return date.fromisoformat(s)  # YYYY-MM-DD
    except ValueError:
        pass

    # Try common formats
    fmts = [
        "%m/%d/%Y", "%m/%d/%y",      # 01/24/2026, 01/24/26
        "%d/%m/%Y", "%d/%m/%y",      # 24/01/2026
        "%m-%d-%Y", "%d-%m-%Y",      # 01-24-2026, 24-01-2026
        "%d.%m.%Y",                  # 24.01.2026
        "%b %d %Y", "%B %d %Y",      # Jan 24 2026, January 24 2026
        "%d %b %Y", "%d %B %Y",      # 24 Jan 2026
    ]
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue

    raise ValueError("Invalid date. Use YYYY-MM-DD or a common format like MM/DD/YYYY.")

class DogBase(BaseModel):
    name: str
    breed: Optional[str]
    sex: Optional[str]
    dob: Optional[date]
    photo_url: Optional[str]

class DogCreate(DogBase):
    name: str
    breed: Optional[str]
    sex: Optional[str]
    dob: Optional[date]
    photo_url: Optional[str]
    
    @field_validator("dob", mode="before")
    @classmethod
    def _parse_dob(cls, v):
        return parse_date_flexible(v)


class DogUpdate(BaseModel):
    name: Optional[str]
    breed: Optional[str]
    sex: Optional[str]
    dob: Optional[date] = None  
    photo_url: Optional[str]

    @field_validator("dob", mode="before")
    @classmethod
    def _parse_dob(cls, v):
        return parse_date_flexible(v)


class DogOut(DogBase):
    dog_id: int
    created_at: datetime

    class Config:
        orm_mode = True
