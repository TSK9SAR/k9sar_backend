from pathlib import Path
import uuid
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from sqlalchemy.orm import Session
from fastapi.responses import FileResponse

from app.database import get_db
from app.utils.auth import get_current_user
from app.models.user import User
from app.models.standard import Standard  # adjust import to your project
from app.models.dog import Dog  # adjust import


router = APIRouter(prefix="/documents", tags=["documents"])

UPLOAD_ROOT = Path("/app/uploads")  # adjust if needed
MAX_BYTES = 25 * 1024 * 1024        # 25 MB
ALLOWED_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
}

@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    standard_id: int | None = Form(None),
    team_id: int | None = Form(None),
    dog_id: int | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    if file.content_type and file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported type: {file.content_type}",
        )

    # ✅ Ensure upload directory exists (no helper needed)
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename).suffix[:10]  # includes leading dot
    stored_filename = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_ROOT / stored_filename

    written = 0
    try:
        with dest.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)  # 1 MB
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_BYTES:
                    out.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail="File too large")
                out.write(chunk)
    finally:
        await file.close()

            # after file is written
    download_url = f"/api/documents/file/{stored_filename}"

    # ✅ If uploading for a standard, store the URL on the standard record
    if standard_id is not None:
        std = db.query(Standard).filter(Standard.standard_id == standard_id).first()
        if not std:
            # optional: delete the uploaded file if standard doesn't exist
            dest.unlink(missing_ok=True)
            raise HTTPException(status_code=404, detail="Standard not found")

        std.url = download_url
        db.commit()

    if dog_id is not None:
        dog = db.query(Dog).filter(Dog.dog_id == dog_id).first()
        if not dog:
            dest.unlink(missing_ok=True)
            raise HTTPException(status_code=404, detail="Dog not found")
        dog.photo_url = download_url
        db.commit()

    return {
        "original_filename": file.filename,
        "stored_filename": stored_filename,
        "content_type": file.content_type,
        "size_bytes": written,
        "download_url": f"/api/documents/file/{stored_filename}",
    }


@router.get("/file/{stored_filename}")
def download_document(stored_filename: str):
    path = UPLOAD_ROOT / stored_filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path)
