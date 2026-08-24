# app/routes/stored_files.py

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.stored_files import StoredFile
from app.services.stored_files import (
    resolve_stored_path,
    save_upload,
)
from app.utils.auth import get_current_user


router = APIRouter(
    prefix="/stored-files",
    tags=["Stored Files"],
)


@router.post("")
async def upload_stored_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    metadata = await save_upload(file)

    stored = StoredFile(
        **metadata,
        uploaded_by_user_id=current_user.user_id,
    )

    db.add(stored)

    try:
        db.commit()
        db.refresh(stored)

    except Exception:
        db.rollback()

        # DB insert failed, so don't leave an orphaned
        # physical file behind.
        try:
            path = resolve_stored_path(
                metadata["storage_path"]
            )
            path.unlink(missing_ok=True)
        except Exception:
            pass

        raise

    return {
        "file_id": stored.file_id,
        "original_filename": stored.original_filename,
        "mime_type": stored.mime_type,
        "file_size": stored.file_size,
        "sha256_hash": stored.sha256_hash,
        "created_at": stored.created_at,
    }