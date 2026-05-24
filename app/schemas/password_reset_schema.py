from pydantic import BaseModel, EmailStr, Field
from typing import Optional

class ForgotIn(BaseModel):
    email: EmailStr

class ResetVerifyOut(BaseModel):
    valid: bool
    reason: Optional[str] = None
    email: Optional[EmailStr] = None

class ResetVerifyIn(BaseModel):
    token: str = Field(min_length=10)

class ResetAcceptIn(BaseModel):
    token: str = Field(min_length=10)
    new_password: str = Field(min_length=8)
    username: Optional[str] = None