from pydantic import BaseModel, EmailStr, constr, validator
from typing import List,Optional
from datetime import datetime
from pydantic.types import StringConstraints
from typing_extensions import Annotated
from app.schemas.discipline_group_schema import DisciplineGroupOut
from sqlalchemy import Column, Boolean, String, DateTime

Password = Annotated[
    str,
    StringConstraints(min_length=8, max_length=72),
]

class UserCreate(BaseModel):
    password: Password  # bcrypt-safe length


class UserBase(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    username: str
    password: Password  
    phone: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state_province: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    domicile_lat: Optional[float] = None
    domicile_lng: Optional[float] = None
    twofa_enabled: bool = False
    twofa_confirmed: bool = False

class UserCreate(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    username: str
    password: Password
    phone: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state_province: str | None = None
    postal_code: str | None = None
    country: str | None = None
    domicile_lat: Optional[float] = None
    domicile_lng: Optional[float] = None

class UserUpdate(BaseModel):
    first_name: Optional[str]
    last_name: Optional[str]
    phone: Optional[str]
    address_line1: Optional[str]
    address_line2: Optional[str]
    city: Optional[str]
    state_province: Optional[str]
    postal_code: Optional[str]
    country: Optional[str]
    domicile_lat: Optional[float]
    domicile_lng: Optional[float]
    is_active: Optional[bool]

class UserOut(BaseModel):
    user_id: int
    username: str
    email: str
    roles: List[str] = []   # list of role names
    is_handler: bool = False
    is_evaluator: bool = False
    is_2fa_verified: bool = False
    discipline_groups: list[DisciplineGroupOut] = []
    is_active: bool
    signature_url: Optional[str] = None
    signature_hash: Optional[str] = None
    signature_updated_at: Optional[datetime] = None

    # class Config:
    #     orm_mode = True
    #     from_attributes = True

    # @validator("roles", pre=True)
    # def extract_role_names(cls, v):
    #     """
    #     When returning ORM objects, `user.roles` is a list of Role objects.
    #     This converts them into a list of role_name strings.
    #     """
    #     try:
    #         return [getattr(role, "role_name", str(role)) for role in v]
    #     except TypeError:
    #         return v

class UserDisciplineGroupsUpdate(BaseModel):
    group_ids: list[int]

# app/schemas/user_schema.py
from pydantic import BaseModel
from typing import Optional

class UserMeUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state_province: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    domicile_lat: Optional[float] = None
    domicile_lng: Optional[float] = None

class UserResponse(BaseModel):
    user_id: int
    first_name: str
    last_name: str
    email: str
    username: Optional[str]
    phone: Optional[str]
    domicile_lat: Optional[float]
    domicile_lng: Optional[float]
    address_line1: Optional[str]
    address_line2: Optional[str]
    city: Optional[str]
    state_province: Optional[str]
    postal_code: Optional[str]
    country: Optional[str]

    signature_url: Optional[str] = None
    signature_hash: Optional[str] = None
    signature_updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True  # equivalent to orm_mode=True in Pydantic v1


    class Config:
        orm_mode = True
