# app/routers/id_headshots.py

from hashlib import sha256

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.utils.auth import get_current_user
from app.models.user import User
from app.models.id_headshot import HandlerIdHeadshot, DogIdHeadshot

router = APIRouter(prefix="/id-headshots", tags=["ID Headshots"])

EXPECTED_WIDTH = 600
EXPECTED_HEIGHT = 900
MAX_BYTES = 3 * 1024 * 1024


def _validate_png(data: bytes) -> None:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=400, detail="File must be a PNG image.")

    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="Image is too large.")


@router.post("/handlers/{handler_id}")
def upload_handler_id_headshot(
    handler_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = file.file.read()
    _validate_png(data)

    db.query(HandlerIdHeadshot).filter(
        HandlerIdHeadshot.handler_id == handler_id,
        HandlerIdHeadshot.is_active == True,
    ).update({"is_active": False})

    row = HandlerIdHeadshot(
        handler_id=handler_id,
        image_png=data,
        sha256_hash=sha256(data).hexdigest(),
        width=EXPECTED_WIDTH,
        height=EXPECTED_HEIGHT,
        uploaded_by_user_id=current_user.user_id,
        is_active=True,
    )

    db.add(row)
    db.commit()
    db.refresh(row)

    return {"headshot_id": row.headshot_id, "handler_id": handler_id}


@router.get("/handlers/{handler_id}")
def get_handler_id_headshot(
    handler_id: int,
    db: Session = Depends(get_db),
):
    row = (
        db.query(HandlerIdHeadshot)
        .filter(
            HandlerIdHeadshot.handler_id == handler_id,
            HandlerIdHeadshot.is_active == True,
        )
        .order_by(HandlerIdHeadshot.headshot_id.desc())
        .first()
    )

    if not row:
        raise HTTPException(status_code=404, detail="No handler ID headshot found.")

    return Response(content=row.image_png, media_type="image/png")


@router.post("/dogs/{dog_id}")
def upload_dog_id_headshot(
    dog_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = file.file.read()
    _validate_png(data)

    db.query(DogIdHeadshot).filter(
        DogIdHeadshot.dog_id == dog_id,
        DogIdHeadshot.is_active == True,
    ).update({"is_active": False})

    row = DogIdHeadshot(
        dog_id=dog_id,
        image_png=data,
        sha256_hash=sha256(data).hexdigest(),
        width=EXPECTED_WIDTH,
        height=EXPECTED_HEIGHT,
        uploaded_by_user_id=current_user.user_id,
        is_active=True,
    )

    db.add(row)
    db.commit()
    db.refresh(row)

    return {"headshot_id": row.headshot_id, "dog_id": dog_id}


@router.get("/dogs/{dog_id}")
def get_dog_id_headshot(
    dog_id: int,
    db: Session = Depends(get_db),
):
    row = (
        db.query(DogIdHeadshot)
        .filter(
            DogIdHeadshot.dog_id == dog_id,
            DogIdHeadshot.is_active == True,
        )
        .order_by(DogIdHeadshot.headshot_id.desc())
        .first()
    )

    if not row:
        raise HTTPException(status_code=404, detail="No dog ID headshot found.")

    return Response(content=row.image_png, media_type="image/png")
