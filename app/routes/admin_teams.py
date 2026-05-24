from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel
from app.database import get_db
from app.utils.auth import require_supervisor, require_mfa_verified
from app.models.team import Team

router = APIRouter(prefix="/admin/teams", tags=["admin-teams"])

class AdminTeamOut(BaseModel):
    team_id: int
    handler_id: int
    dog_id: int
    status: Optional[str] = None

    class Config:
        from_attributes = True  # pydantic v2

class AdminTeamPatch(BaseModel):
    status: Optional[str] = None

@router.get("/{team_id}", response_model=AdminTeamOut)
def admin_get_team(
    team_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_supervisor),
):
    t = db.query(Team).filter(Team.team_id == team_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Team not found")
    return t

@router.patch("/{team_id}", response_model=AdminTeamOut)
def admin_patch_team(
    team_id: int,
    payload: AdminTeamPatch,
    db: Session = Depends(get_db),
    current_user=Depends(require_supervisor),
    _mfa=Depends(require_mfa_verified),  # <-- add this
):
    t = db.query(Team).filter(Team.team_id == team_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Team not found")

    if payload.status is not None:
        t.status = payload.status

    db.add(t)
    db.commit()
    db.refresh(t)
    return t
