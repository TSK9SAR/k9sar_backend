import os
from pathlib import Path
import mimetypes
from app.utils.auth import get_current_user
from fastapi import APIRouter, Depends, HTTPException, Response
import hmac
import hashlib
import time
from urllib.parse import urlencode
import re
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.help import HelpItemVideo  # adjust import path


from fastapi import Query

router = APIRouter(prefix="/help-videos", tags=["help-videos"])

VIDEO_ROOT = Path("/var/sark9/private_videos").resolve()


VIDEO_SIGNING_SECRET = os.getenv("VIDEO_SIGNING_SECRET", "change-me")

def make_video_sig(video_id: str, exp: int) -> str:
    msg = f"{video_id}:{exp}".encode("utf-8")
    secret = VIDEO_SIGNING_SECRET.encode("utf-8")
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()

def verify_video_sig(video_id: str, exp: int, sig: str) -> bool:
    if exp < int(time.time()):
        return False
    expected = make_video_sig(video_id, exp)
    return hmac.compare_digest(expected, sig)

def get_user_role_names(current_user) -> set[str]:
    role_names = set()

    # adapt if your current_user shape differs
    for r in getattr(current_user, "roles", []) or []:
        name = getattr(r, "role_name", None)
        if name:
            role_names.add(name.lower())

    # optional fallback if /auth/me-style role strings are already present
    for name in getattr(current_user, "role_names", []) or []:
        if name:
            role_names.add(str(name).lower())

    return role_names

@router.get("/{video_id}/play-url")
def get_help_video_play_url(
    video_id: str,
    current_user=Depends(get_current_user),
):

    safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "", video_id)

    if safe_id != video_id:
        raise HTTPException(status_code=400, detail="Invalid video id")

    rel_path = f"{safe_id}.mp4"
    path = (VIDEO_ROOT / rel_path).resolve()

    if VIDEO_ROOT not in path.parents and path != VIDEO_ROOT:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not path.exists():
        raise HTTPException(status_code=404, detail="Video not found")

    exp = int(time.time()) + 300
    sig = make_video_sig(video_id, exp)

    return {
        "url": f"/api/help-videos/{video_id}/stream?exp={exp}&sig={sig}"
    }

@router.get("/")
def list_help_videos(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return (
        db.query(HelpItemVideo)
        .filter(HelpItemVideo.is_active.is_(True))
        .order_by(HelpItemVideo.sort_order, HelpItemVideo.video_id)
        .all()
    )

@router.get("/{video_id}/stream")
def stream_help_video(
    video_id: str,
    exp: int = Query(...),
    sig: str = Query(...),
):
    if not verify_video_sig(video_id, exp, sig):
        raise HTTPException(status_code=403, detail="Invalid or expired video link")

    safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "", video_id)

    if safe_id != video_id:
        raise HTTPException(status_code=400, detail="Invalid video id")

    # Legacy files live in /var/sark9/private_videos/help/{video_key}.mp4
    rel_path = f"{safe_id}.mp4"
    abs_path = (VIDEO_ROOT / rel_path).resolve()

    if VIDEO_ROOT not in abs_path.parents and abs_path != VIDEO_ROOT:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not abs_path.exists() or not abs_path.is_file():
        raise HTTPException(status_code=404, detail="Video file missing")

    media_type, _ = mimetypes.guess_type(str(abs_path))
    media_type = media_type or "application/octet-stream"

    response = Response()
    response.headers["X-Accel-Redirect"] = f"/_protected_videos/{rel_path}"
    response.headers["Content-Type"] = media_type
    response.headers["Accept-Ranges"] = "bytes"
    response.headers["Cache-Control"] = "private, no-store"
    return response
