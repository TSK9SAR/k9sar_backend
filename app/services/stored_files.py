import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.stored_files import (
    StoredFile,
    ForumPostAttachment,
    EmailCampaignAttachment,
)


STORED_FILE_ROOT = Path(
    os.getenv("STORED_FILE_ROOT", "/app/uploads/files")
).resolve()

MAX_FILE_SIZE = int(
    os.getenv(
        "STORED_FILE_MAX_BYTES",
        str(20 * 1024 * 1024),
    )
)

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".csv",
    ".txt",
    ".jpg",
    ".jpeg",
    ".png",
}


def ensure_storage_root() -> None:
    STORED_FILE_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )


def normalize_filename(filename: str | None) -> str:
    name = Path(filename or "file").name.strip()

    if not name:
        return "file"

    return name[:255]


def validate_extension(filename: str) -> None:
    extension = Path(filename).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File type '{extension or 'unknown'}' "
                "is not allowed."
            ),
        )


def build_storage_location(
    original_filename: str,
) -> tuple[str, Path]:
    now = datetime.now(timezone.utc)

    extension = Path(
        original_filename
    ).suffix.lower()

    stored_filename = (
        f"{uuid.uuid4().hex}{extension}"
    )

    relative_path = Path(
        str(now.year),
        f"{now.month:02d}",
        stored_filename,
    )

    absolute_path = (
        STORED_FILE_ROOT / relative_path
    ).resolve()

    if (
        absolute_path != STORED_FILE_ROOT
        and STORED_FILE_ROOT
        not in absolute_path.parents
    ):
        raise RuntimeError(
            "Invalid stored file path"
        )

    absolute_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    return (
        relative_path.as_posix(),
        absolute_path,
    )


async def save_upload(
    file: UploadFile,
) -> dict:
    ensure_storage_root()

    original_filename = normalize_filename(
        file.filename
    )

    validate_extension(
        original_filename
    )

    storage_path, absolute_path = (
        build_storage_location(
            original_filename
        )
    )

    sha256 = hashlib.sha256()
    total_size = 0

    try:
        with absolute_path.open("xb") as out:
            while True:
                chunk = await file.read(
                    1024 * 1024
                )

                if not chunk:
                    break

                total_size += len(chunk)

                if total_size > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            "File exceeds maximum size "
                            f"of "
                            f"{MAX_FILE_SIZE // (1024 * 1024)} MB."
                        ),
                    )

                sha256.update(chunk)
                out.write(chunk)

    except Exception:
        absolute_path.unlink(
            missing_ok=True
        )
        raise

    return {
        "original_filename":
            original_filename,

        "stored_filename":
            absolute_path.name,

        "mime_type":
            file.content_type,

        "file_size":
            total_size,

        "sha256_hash":
            sha256.hexdigest(),

        "storage_path":
            storage_path,
    }


def resolve_stored_path(
    storage_path: str,
) -> Path:
    path = (
        STORED_FILE_ROOT / storage_path
    ).resolve()

    if (
        path != STORED_FILE_ROOT
        and STORED_FILE_ROOT
        not in path.parents
    ):
        raise RuntimeError(
            "Stored file path escapes storage root"
        )

    return path


def delete_physical_file(
    storage_path: str,
) -> bool:
    path = resolve_stored_path(
        storage_path
    )

    if not path.exists():
        return False

    path.unlink()
    return True


def stored_file_reference_count(
    db: Session,
    file_id: int,
) -> int:
    forum_count = (
        db.query(
            func.count(
                ForumPostAttachment.attachment_id
            )
        )
        .filter(
            ForumPostAttachment.file_id
            == file_id
        )
        .scalar()
        or 0
    )

    campaign_count = (
        db.query(
            func.count(
                EmailCampaignAttachment.attachment_id
            )
        )
        .filter(
            EmailCampaignAttachment.file_id
            == file_id
        )
        .scalar()
        or 0
    )

    return (
        int(forum_count)
        + int(campaign_count)
    )


def delete_stored_file_if_unreferenced(
    db: Session,
    stored_file: StoredFile,
) -> bool:
    if stored_file_reference_count(
        db,
        stored_file.file_id,
    ) > 0:
        return False

    delete_physical_file(
        stored_file.storage_path
    )

    db.delete(stored_file)

    return True