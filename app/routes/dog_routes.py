from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.dog import Dog
from app.schemas.dog_schema import DogCreate, DogOut, DogUpdate
from app.utils.auth import get_current_user
from datetime import datetime
from app.utils.authz import require_supervisor_or_admin, require_member
from app.models.user import User
from app.models.handler import Handler
from app.models.dog import Dog
from app.models.team import Team


router = APIRouter(prefix="/dogs", tags=["Dogs"])



@router.get("/search")
def search_dogs(
    q: Optional[str] = Query(None),
    query: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    term = (q or query or "").strip()
    if not term:
        return []

    like = f"%{term}%"

    rows = (
        db.query(Dog)
        .filter((Dog.name.ilike(like)) | (Dog.breed.ilike(like)))
        .order_by(Dog.name.asc())
        .limit(limit)
        .all()
    )

    return [
        {
            "dog_id": d.dog_id,
            "name": d.name,
            "breed": d.breed,
            "sex": d.sex,
            "dob": d.dob,
            "photo_url": getattr(d, "photo_url", None),
        }
        for d in rows
    ]

@router.post("/", response_model=DogOut)
def create_dog(dog: DogCreate,
               db: Session = Depends(get_db),
               current_user = Depends(get_current_user)):
    require_member(current_user)
    new_dog = Dog(**dog.dict())
    db.add(new_dog)
    db.commit()
    db.refresh(new_dog)
    return new_dog

@router.get("/{dog_id}", response_model=DogOut)
def get_dog(dog_id: int, db: Session = Depends(get_db), current_user = Depends(get_current_user)):
    dog = db.query(Dog).filter(Dog.dog_id == dog_id).first()
    if not dog:
        raise HTTPException(status_code=404, detail="Dog not found")
    return dog

@router.put("/{dog_id}", response_model=DogOut)
def update_dog(dog_id: int, update: DogUpdate,
               db: Session = Depends(get_db),
               current_user = Depends(get_current_user)):
    dog = db.query(Dog).filter(Dog.dog_id == dog_id).first()
    if not dog:
        raise HTTPException(status_code=404, detail="Dog not found")
    for k, v in update.dict(exclude_unset=True).items():
        setattr(dog, k, v)
    db.commit()
    db.refresh(dog)
    return dog


def ensure_handler(db: Session, user_id: int) -> Handler:
    handler = db.query(Handler).filter(Handler.user_id == user_id).first()
    if handler:
        return handler
    handler = Handler(user_id=user_id)
    db.add(handler)
    db.flush()
    return handler

@router.post("")
def add_dog(payload: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # payload:
    # { "dog": { "name": "...", ... } }
    # { "user_id": 123, "dog": {...} }  # elevated acting for someone else

    target_user_id = payload.get("user_id", current_user.user_id)
    if target_user_id != current_user.user_id:
        require_supervisor_or_admin(current_user)

    dog_data = payload.get("dog") or {}
    if not dog_data.get("name"):
        raise HTTPException(status_code=422, detail="dog.name is required")

    try:
        handler = ensure_handler(db, target_user_id)

        dog = Dog(
            name=dog_data["name"],
            breed=dog_data.get("breed"),
            sex=dog_data.get("sex"),
            dob=dog_data.get("dob"),
            photo_url=dog_data.get("photo_url"),
        )
        db.add(dog)
        db.flush()

        # create the pairing team row (this is the “team” in your schema)
        team = Team(handler_id=handler.handler_id, dog_id=dog.dog_id, status="active")
        db.add(team)
        db.flush()

        db.commit()
        return {
            "dog_id": dog.dog_id,
            "team_id": team.team_id,
            "handler_id": handler.handler_id,
        }
    except Exception:
        db.rollback()
        raise
