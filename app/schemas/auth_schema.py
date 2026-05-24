from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    user_id: Optional[int] = None
    roles: Optional[List[str]] = None  # 👈 list of role names

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class OAuthLoginRequest(BaseModel):
    provider: str   # "google" or "microsoft"
    code: str       # OAuth2 authorization code

class MeOut(BaseModel):
    user_id: int
    first_name: str | None = None
    last_name: str | None = None
    email: str
    roles: list[str] = []
    city: str | None = None
    state: str | None = None
    country: str | None = None
    domicile_lat: float | None = None
    domicile_lng: float | None = None
    priv: str
    allowed_standard_ids: list[int] = []

class ReauthPasswordIn(BaseModel):
    password: str = Field(..., min_length=1, description="Current account password")

    def normalized_password(self) -> str:
        return self.password.strip()