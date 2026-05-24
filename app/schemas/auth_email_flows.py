from pydantic import BaseModel, EmailStr, Field

class ForgotIn(BaseModel):
    email: EmailStr



class AdminInviteCreateIn(BaseModel):
    email: EmailStr
    team_id: int
    role_id: int | None = None

class InviteVerifyIn(BaseModel):
    token: str = Field(min_length=10)

class InviteAcceptIn(BaseModel):
    token: str = Field(min_length=10)
    # optionally add: first_name/last_name/password if you're creating user here
