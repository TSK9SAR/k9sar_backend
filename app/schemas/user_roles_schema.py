# app/schemas/user_roles_schema.py
from pydantic import BaseModel, Field
from typing import List

class UserRolesUpdate(BaseModel):
    role_names: List[str] = Field(default_factory=list)  # e.g. ["member","supervisor"]
