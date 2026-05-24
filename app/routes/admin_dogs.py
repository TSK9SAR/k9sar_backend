from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel
from datetime import date, datetime
from app.database import get_db
from app.utils.auth import require_supervisor, require_mfa_verified
from app.models.dog import Dog

router = APIRouter(prefix="/admin/dogs", tags=["admin-dogs"])

class AdminDogOut(BaseModel):
    dog_id: int
    name: Optional[str] = None
    breed: Optional[str] = None
    sex: Optional[str] = None
    dob: Optional[date] = None
    photo_url: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True  # pydantic v2

class AdminDogPatch(BaseModel):
    name: Optional[str] = None
    breed: Optional[str] = None
    sex: Optional[str] = None
    dob: Optional[date] = None
    photo_url: Optional[str] = None

@router.get("/{dog_id}", response_model=AdminDogOut)
def admin_get_dog(
    dog_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_supervisor),
):
    d = db.query(Dog).filter(Dog.dog_id == dog_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Dog not found")
    return d

@router.patch("/{dog_id}", response_model=AdminDogOut)
def admin_patch_dog(
    dog_id: int,
    payload: AdminDogPatch,
    db: Session = Depends(get_db),
    current_user=Depends(require_supervisor),
    _mfa=Depends(require_mfa_verified),  # <-- add this
):
    d = db.query(Dog).filter(Dog.dog_id == dog_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Dog not found")

    # Only update provided fields
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(d, k, v)

    db.add(d)
    db.commit()
    db.refresh(d)
    return d
