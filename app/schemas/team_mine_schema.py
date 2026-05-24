# app/schemas/team_mine_schema.py
from typing import Optional, List
from pydantic import BaseModel

class DogOut(BaseModel):
    dog_id: int
    name: str
    breed: Optional[str] = None
    photo_url: Optional[str] = None

class MyTeamOut(BaseModel):
    team_id: int
    status: Optional[str] = None
    dog: DogOut

class MyTeamsOut(BaseModel):
    handler_id: Optional[int] = None
    handler_status: Optional[str] = None
    teams: List[MyTeamOut] = []
