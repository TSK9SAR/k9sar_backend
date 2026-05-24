from pydantic import BaseModel
from typing import Optional

# app/schemas/discipline_schema.py
from pydantic import BaseModel
from typing import Optional

class DisciplineOut(BaseModel):
    discipline_id: int
    name: str
    group_id: int
    sortorder: int
    show_operational: bool
    show_generic: bool

class DisciplineCreate(BaseModel):
    name: str
    description: str | None = None
    group_id: int | None = None
    sortorder: int | None = None
    show_operational: bool | None = None
    show_generic: bool | None = None

class DisciplineUpdate(BaseModel):
    group_id: Optional[int] = None
    name: Optional[str] = None
    sortorder: Optional[int] = None
    description: Optional[str] = None
    show_operational: bool | None = None
    show_generic: bool | None = None

class DisciplineOut(BaseModel):
    discipline_id: int
    group_id: int
    name: str
    description: str | None
    sortorder: int
    show_operational: bool
    show_generic: bool

    class Config:
        orm_mode = True
