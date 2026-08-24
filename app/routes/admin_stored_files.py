from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.stored_files import StoredFile
from app.services.stored_files import (
    delete_stored_file_if_unreferenced,
    resolve_stored_path,
    save_upload,
    stored_file_reference_count,
)
from app.utils.auth import require_admin


router = APIRouter(
    prefix="/admin/stored-files",
    tags=["Admin Stored Files"],
)


@router.post("")
async def upload_stored_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
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

        # The physical file was already written.
        # Remove it if the database row could not be created.
        try:
            path = resolve_stored_path(metadata["storage_path"])
            path.unlink(missing_ok=True)
        except Exception:
            pass

        raise

    return {
        "file_id": stored.file_id,
        "original_filename": stored.original_filename,
        "stored_filename": stored.stored_filename,
        "mime_type": stored.mime_type,
        "file_size": stored.file_size,
        "sha256_hash": stored.sha256_hash,
        "storage_path": stored.storage_path,
        "uploaded_by_user_id": stored.uploaded_by_user_id,
        "created_at": stored.created_at,
        "reference_count": 0,
    }


@router.get("/{file_id}")
def download_stored_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    stored = (
        db.query(StoredFile)
        .filter(StoredFile.file_id == file_id)
        .first()
    )

    if not stored:
        raise HTTPException(
            status_code=404,
            detail="Stored file not found.",
        )

    path = resolve_stored_path(stored.storage_path)

    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Stored file exists in the database but is missing from storage.",
        )

    return FileResponse(
        path=str(path),
        media_type=stored.mime_type or "application/octet-stream",
        filename=stored.original_filename,
    )


@router.get("/{file_id}/info")
def stored_file_info(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    stored = (
        db.query(StoredFile)
        .filter(StoredFile.file_id == file_id)
        .first()
    )

    if not stored:
        raise HTTPException(
            status_code=404,
            detail="Stored file not found.",
        )

    path = resolve_stored_path(stored.storage_path)

    return {
        "file_id": stored.file_id,
        "original_filename": stored.original_filename,
        "stored_filename": stored.stored_filename,
        "mime_type": stored.mime_type,
        "file_size": stored.file_size,
        "sha256_hash": stored.sha256_hash,
        "storage_path": stored.storage_path,
        "uploaded_by_user_id": stored.uploaded_by_user_id,
        "created_at": stored.created_at,
        "reference_count": stored_file_reference_count(
            db,
            stored.file_id,
        ),
        "physical_file_exists": path.exists(),
    }


@router.delete("/{file_id}")
def delete_stored_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    stored = (
        db.query(StoredFile)
        .filter(StoredFile.file_id == file_id)
        .first()
    )

    if not stored:
        raise HTTPException(
            status_code=404,
            detail="Stored file not found.",
        )

    reference_count = stored_file_reference_count(
        db,
        stored.file_id,
    )

    if reference_count > 0:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Stored file is still referenced "
                f"{reference_count} time(s) and cannot be deleted."
            ),
        )

    deleted = delete_stored_file_if_unreferenced(
        db,
        stored,
    )

    if not deleted:
        raise HTTPException(
            status_code=409,
            detail="Stored file is still referenced and cannot be deleted.",
        )

    db.commit()

    return {
        "status": "deleted",
        "file_id": file_id,
    }