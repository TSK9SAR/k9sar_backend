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

    # Fast path: ISO
    try:
        return date.fromisoformat(s)  # YYYY-MM-DD
    except ValueError:
        pass

    fmts = [
        "%m/%d/%Y", "%m/%d/%y",
        "%d/%m/%Y", "%d/%m/%y",
        "%m-%d-%Y", "%d-%m-%Y",
        "%d.%m.%Y",
        "%b %d %Y", "%B %d %Y",
        "%d %b %Y", "%d %B %Y",
    ]
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue

    raise ValueError("Invalid date. Use YYYY-MM-DD or a common format like MM/DD/YYYY.")


class StandardCreate(BaseModel):
    discipline_id: int
    name: str
    url: str | None = None
    summary_md: str | None = None
    effective_date: date
    incomplete_days: int | None = None  # days the incomplete status remains.
    effective_days: int | None = None  # days the standard is effective after the effective_date.

    @field_validator("effective_date", mode="before")
    @classmethod
    def _parse_implementation_date(cls, v):
        return parse_date_flexible(v)


class StandardUpdate(BaseModel):
    discipline_id: int | None = None
    name: str | None = None
    summary_md: str | None = None
    url: str | None = None
    effective_date: date | None = None
    incomplete_days: int | None = None  # days the incomplete status remains.
    effective_days: int | None = None  # days the standard is effective after the effective_date.

    @field_validator("effective_date", mode="before")
    @classmethod
    def _parse_implementation_date(cls, v):
        return parse_date_flexible(v)


from pydantic import BaseModel, ConfigDict

class StandardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    standard_id: int
    discipline_id: int | None = None
    name: str
    effective_date: date | None = None  # or date | None if you use date
    summary_md: str | None = None
    url: str | None = None
    incomplete_days: int | None = None
    effective_days: int | None = None

    discipline_name: str | None = None
    discipline_group_id: int | None = None
    discipline_group_name: str | None = None
    discipline_sortorder: int | None = None
    discipline_group_sortorder: int | None = None


class StandardPublicOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    standard_id: int
    discipline_id: int
    name: str
    summary_md: Optional[str] = None
    url: Optional[str] = None
    effective_date: date
    incomplete_days: Optional[int] = None
    effective_days: Optional[int] = None
    # ✅ add these
    discipline_name: Optional[str] = None
    discipline_group_id: Optional[int] = None
    discipline_group_name: Optional[str] = None
    discipline_sortorder: int | None = None
    discipline_group_sortorder: int | None = None



class DisciplineWithLatestStandardOut(BaseModel):
    discipline_id: int
    group_id: int
    name: str
    description: Optional[str] = None
    sortorder: int
    standard: Optional[StandardPublicOut] = None
    incomplete_days: Optional[int] = None
    effective_days: Optional[int] = None

    class Config:
        orm_mode = True

