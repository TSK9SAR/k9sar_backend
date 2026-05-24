# app/models/standard.py
from datetime import date
from sqlalchemy import Column, Integer, String, ForeignKey, Date, Index, Text
from sqlalchemy.orm import relationship
from app.database import Base

from app.models.discipline import Discipline   # ← ADD THIS


from datetime import date

from datetime import date, datetime
from typing import Any
from pydantic import BaseModel, Field, field_validator

from sqlalchemy import func, and_
from sqlalchemy.orm import aliased


def get_active_standard(db, discipline_id: int):
    return (
        db.query(Standard)
        .filter(Standard.discipline_id == discipline_id)
        .filter(Standard.effective_date <= date.today())
        .order_by(Standard.effective_date.desc())
        .first()
    )


def parse_date_flexible(v: Any) -> date | None:
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



class Standard(Base):
    __tablename__ = "standards"

    standard_id = Column(Integer, primary_key=True, index=True)

    discipline_id = Column(
        Integer,
        ForeignKey("disciplines.discipline_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name = Column(String(200), nullable=False)
    summary_md = Column(Text, nullable=True)
    url = Column(String(500), nullable=True)
    incomplete_days = Column(Integer, nullable=True, default=0)
    effective_days = Column(Integer, nullable=True, default=730)
    # renamed + defaults to today; NOT NULL
    effective_date = Column(Date, nullable=False, default=date.today)

    discipline = relationship("Discipline", back_populates="standards")
    certifications = relationship("Certification", back_populates="standard")

    __table_args__ = (
        # fast “active standard” lookup
        Index("ix_standards_discipline_effective_date", "discipline_id", "effective_date"),

        # enforce uniqueness in-scope (recommended)
        # if you want to allow multiple standards same day, remove this
        # UniqueConstraint("discipline_id", "effective_date", name="uq_standards_discipline_effective_date"),

        # if you want name uniqueness per discipline instead of global:
        # UniqueConstraint("discipline_id", "name", name="uq_standards_discipline_name"),
    )

    # documents = relationship("Document", back_populates="standard")

def query_disciplines_with_latest_standard(db):
    today = date.today()

    # max effective_date per discipline where effective_date <= today
    latest_dt_subq = (
        db.query(
            Standard.discipline_id.label("discipline_id"),
            func.max(Standard.effective_date).label("max_eff"),
        )
        .filter(Standard.effective_date <= today)
        .group_by(Standard.discipline_id)
        .subquery()
    )

    # tie-break: max standard_id among rows at max_eff
    latest_id_subq = (
        db.query(
            Standard.discipline_id.label("discipline_id"),
            func.max(Standard.standard_id).label("max_id"),
        )
        .join(
            latest_dt_subq,
            and_(
                latest_dt_subq.c.discipline_id == Standard.discipline_id,
                latest_dt_subq.c.max_eff == Standard.effective_date,
            ),
        )
        .group_by(Standard.discipline_id)
        .subquery()
    )

    S = aliased(Standard)

    rows = (
        db.query(Discipline, S)
        .outerjoin(latest_id_subq, latest_id_subq.c.discipline_id == Discipline.discipline_id)
        .outerjoin(S, S.standard_id == latest_id_subq.c.max_id)
        .order_by(Discipline.sortorder.asc(), Discipline.name.asc())
        .all()
    )

    return rows  # list[(Discipline, Standard|None)]


class StandardCreate(BaseModel):
    discipline_id: int
    name: str
    url: str | None = None
    summary_md: str | None = None

    # defaults to today unless explicitly provided
    effective_date: date = Field(default_factory=date.today)

    @field_validator("effective_date", mode="before")
    @classmethod
    def _parse_effective_date(cls, v):
        parsed = parse_date_flexible(v)
        return parsed if parsed is not None else date.today()


class StandardUpdate(BaseModel):
    discipline_id: int | None = None
    name: str | None = None
    url: str | None = None
    summary_md: str | None = None   
    effective_date: date | None = None
    incomplete_days: int | None = None  # days the incomplete status remains.
    effective_days: int | None = None  # days the standard is effective after the effective_date.

    @field_validator("effective_date", mode="before")
    @classmethod
    def _parse_effective_date(cls, v):
        return parse_date_flexible(v)


class StandardOut(BaseModel):
    standard_id: int
    discipline_id: int
    name: str
    summary_md: str | None = None
    url: str | None = None
    effective_date: date
    incomplete_days: int
    effective_days: int

    class Config:
        orm_mode = True


