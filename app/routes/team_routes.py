# app/routes/team_routes.py
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.team import Team
# from app.models.handler import Handler
from app.models.dog import Dog
from app.schemas.team_schema import TeamCreate, TeamUpdate, TeamOut
from typing import List
from sqlalchemy.orm import Session, joinedload
from app.utils.auth import get_current_user
from app.models.user import User
from app.schemas.team_mine_schema import MyTeamsOut, MyTeamOut, DogOut
from sqlalchemy import and_, func
from app.services.handler_service import get_or_create_handler_for_user
from app.utils.auth import current_user_id

router = APIRouter(prefix="/teams", tags=["Teams"])

@router.get("/mine", response_model=MyTeamsOut)
def my_teams(
    include_inactive: bool = Query(False, description="Include inactive teams"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # If user has no handler yet, they have no teams.
    if not current_user.handler:
        return MyTeamsOut(handler_id=None, handler_status=None, teams=[])

    handler_id = current_user.handler.handler_id

    q = (
        db.query(Team)
        .options(joinedload(Team.dog))
        .filter(Team.handler_id == handler_id)
    )

    if not include_inactive:
        q = q.filter(Team.status != "inactive")

    q = q.order_by(Team.team_id.asc())
    teams = q.all()

    out = [
        MyTeamOut(
            team_id=t.team_id,
            status=t.status,
            dog=DogOut(
                dog_id=t.dog.dog_id,
                name=t.dog.name,
                breed=t.dog.breed,
                photo_url=t.dog.photo_url,
            ),
        )
        for t in teams
    ]

    return MyTeamsOut(
        handler_id=handler_id,
        handler_status=current_user.handler.status,
        teams=out,
    )



@router.post("/", response_model=TeamOut)
def create_team(payload: TeamCreate,
                db: Session = Depends(get_db),
                current_user=Depends(get_current_user)):

    # validate dog exists (and optionally permissions)
    dog = db.query(Dog).filter(Dog.dog_id == payload.dog_id).first()
    if not dog:
        raise HTTPException(status_code=404, detail="Dog not found")

    # ensure handler exists for current user
    uid = current_user_id(current_user)
    handler = get_or_create_handler_for_user(db, uid)

    # optional: prevent duplicate team for same handler+dog
    existing = (
        db.query(Team)
        .filter(Team.handler_id == handler.handler_id, Team.dog_id == payload.dog_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Team already exists for this dog")

    team = Team(handler_id=handler.handler_id, dog_id=payload.dog_id, status=payload.status)
    db.add(team)
    db.commit()
    db.refresh(team)
    return team



@router.get("/", response_model=List[TeamOut])
def get_teams(db: Session = Depends(get_db)):
    return db.query(Team).all()

@router.get("/{team_id}", response_model=TeamOut)
def get_team(team_id: int, db: Session = Depends(get_db)):
    team = db.query(Team).filter(Team.team_id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


@router.put("/{team_id}", response_model=TeamOut)
def update_team(team_id: int, updates: TeamUpdate, db: Session = Depends(get_db)):
    team = db.query(Team).filter(Team.team_id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    for key, value in updates.model_dump(exclude_unset=True).items():
        setattr(team, key, value)

    db.commit()
    db.refresh(team)
    return team




@router.delete("/{team_id}", status_code=204)
def deactivate_team(
    team_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    team = db.query(Team).filter(Team.team_id == team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    team.status = "inactive"  # or delete row
    db.commit()
    return

