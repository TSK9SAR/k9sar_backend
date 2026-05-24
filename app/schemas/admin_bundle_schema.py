from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class AdminTeamOut(BaseModel):
    team_id: int
    team_name: Optional[str] = None
    status: Optional[str] = None

    class Config:
        from_attributes = True


class AdminDogOut(BaseModel):
    dog_id: int
    dog_name: Optional[str] = None
    status: Optional[str] = None

    class Config:
        from_attributes = True


class AdminUserBundleOut(BaseModel):
    user: Dict[str, Any]
    handler: Optional[Dict[str, Any]] = None
    teams: List[Dict[str, Any]] = []
    dogs: List[Dict[str, Any]] = []
