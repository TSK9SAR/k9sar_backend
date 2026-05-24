# app/schemas/discipline_group_schema.py

from pydantic import BaseModel, Field

class DisciplineGroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    sortorder: int = 100
    discipline_ids: list[int] = Field(default_factory=list)
    show_operational: bool = True
    show_generic: bool = False

class DisciplineGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    sortorder: int | None = None
    discipline_ids: list[int] | None = None  # if provided, REPLACE the set
    show_operational: bool | None = None
    show_generic: bool | None = None

class DisciplineGroupOut(BaseModel):
    group_id: int
    name: str
    sortorder: int = 0
    discipline_ids: list[int] = []
    show_operational: bool
    show_generic: bool

    class Config:
        from_attributes = True
