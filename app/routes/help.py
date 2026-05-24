from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models.help import HelpSection, HelpItem, HelpItemVideo
from app.schemas.help import (
    HelpSectionOut,
    HelpSectionIn,
    HelpItemIn,
    HelpVideoIn,
)

# adjust these imports to your actual auth helpers
from app.utils.auth import get_current_user, require_admin

import re
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import File, Form, UploadFile

PRIVATE_VIDEO_DIR = Path("/var/sark9/private_videos")
MAX_HELP_VIDEO_BYTES = 500 * 1024 * 1024  # 500 MB

router = APIRouter(prefix="/help", tags=["help"])


@router.get("", response_model=list[HelpSectionOut])
def public_help(db: Session = Depends(get_db)):
    sections = (
        db.query(HelpSection)
        .options(
            selectinload(HelpSection.items).selectinload(HelpItem.videos)
        )
        .filter(HelpSection.is_active.is_(True))
        .order_by(HelpSection.sort_order, HelpSection.title)
        .all()
    )

    for section in sections:
        section.items = sorted(
            [i for i in section.items if i.is_active],
            key=lambda i: (i.sort_order, i.title),
        )
        for item in section.items:
            item.videos = sorted(
                [v for v in item.videos if v.is_active],
                key=lambda v: (v.sort_order, v.video_id),
            )

    return sections

admin_router = APIRouter(prefix="/admin/help", tags=["admin-help"])


@admin_router.get("", response_model=list[HelpSectionOut])
def admin_help(
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):

    return (
        db.query(HelpSection)
        .options(selectinload(HelpSection.items).selectinload(HelpItem.videos))
        .order_by(HelpSection.sort_order, HelpSection.title)
        .all()
    )


@admin_router.post("/sections", response_model=HelpSectionOut)
def create_section(
    payload: HelpSectionIn,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):

    section = HelpSection(**payload.model_dump())
    db.add(section)
    db.commit()
    db.refresh(section)
    return section


@admin_router.put("/sections/{section_id}", response_model=HelpSectionOut)
def update_section(
    section_id: int,
    payload: HelpSectionIn,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):

    section = db.get(HelpSection, section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Help section not found")

    for key, value in payload.model_dump().items():
        setattr(section, key, value)

    db.commit()
    db.refresh(section)
    return section


@admin_router.post("/items")
def create_item(
    payload: HelpItemIn,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):

    existing = db.query(HelpItem).filter(HelpItem.slug == payload.slug).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="A help item with this slug already exists."
        )
    
    item = HelpItem(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@admin_router.put("/items/{help_id}")
def update_item(
    help_id: int,
    payload: HelpItemIn,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    existing = (
        db.query(HelpItem)
        .filter(HelpItem.slug == payload.slug, HelpItem.help_id != help_id)
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=400,
            detail="A help item with this slug already exists."
        )

    item = db.get(HelpItem, help_id)
    if not item:
        raise HTTPException(status_code=404, detail="Help item not found")

    for key, value in payload.model_dump().items():
        setattr(item, key, value)

    db.commit()
    db.refresh(item)
    return item


@admin_router.delete("/items/{help_id}")
def delete_item(
    help_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    item = db.get(HelpItem, help_id)
    if not item:
        raise HTTPException(status_code=404, detail="Help item not found")

    db.delete(item)
    db.commit()
    return {"ok": True}


@admin_router.post("/items/{help_id}/videos")
def create_video(
    help_id: int,
    payload: HelpVideoIn,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):

    item = db.get(HelpItem, help_id)
    if not item:
        raise HTTPException(status_code=404, detail="Help item not found")

    video = HelpItemVideo(help_id=help_id, **payload.model_dump())
    db.add(video)
    db.commit()
    db.refresh(video)
    return video


@admin_router.put("/videos/{video_id}")
def update_video(
    video_id: int,
    payload: HelpVideoIn,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):

    video = db.get(HelpItemVideo, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Help video not found")

    for key, value in payload.model_dump().items():
        setattr(video, key, value)

    db.commit()
    db.refresh(video)
    return video


@admin_router.delete("/videos/{video_id}")
def delete_video(
    video_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):
    video = db.get(HelpItemVideo, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Help video not found")

    db.delete(video)
    db.commit()
    return {"ok": True}

@admin_router.post("/items/{help_id}/videos/upload")
def upload_help_video(
    help_id: int,
    file: UploadFile = File(...),
    label: str = Form(""),
    sort_order: int = Form(0),
    is_active: bool = Form(True),
    db: Session = Depends(get_db),
    current_user=Depends(require_admin),
):

    item = db.get(HelpItem, help_id)
    if not item:
        raise HTTPException(status_code=404, detail="Help item not found")

    original_name = file.filename or ""
    suffix = Path(original_name).suffix.lower()

    if suffix != ".mp4":
        raise HTTPException(status_code=400, detail="Only MP4 videos are supported.")

    PRIVATE_VIDEO_DIR.mkdir(parents=True, exist_ok=True)

    safe_base = re.sub(r"[^a-zA-Z0-9_-]+", "-", Path(original_name).stem).strip("-").lower()
    safe_base = safe_base[:60] or "help-video"

    video_key = f"{safe_base}-{uuid4().hex[:10]}"
    target_path = PRIVATE_VIDEO_DIR / f"{video_key}.mp4"

    bytes_written = 0

    try:
        with target_path.open("wb") as out:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break

                bytes_written += len(chunk)

                if bytes_written > MAX_HELP_VIDEO_BYTES:
                    out.close()
                    target_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail="Video is too large. Maximum size is 500 MB.",
                    )

                out.write(chunk)
    finally:
        file.file.close()

    if not target_path.exists() or target_path.stat().st_size == 0:
        raise HTTPException(status_code=500, detail="Upload failed")

    video = HelpItemVideo(
        help_id=help_id,
        video_key=video_key,
        label=label.strip() or Path(original_name).stem,
        sort_order=sort_order,
        is_active=is_active,
    )

    db.add(video)
    db.commit()
    db.refresh(video)

    return video