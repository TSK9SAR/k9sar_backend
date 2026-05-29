from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
from fastapi.responses import FileResponse
from PIL import Image, ImageOps
from sqlalchemy.orm import Session
from sqlalchemy import select, text 
from io import BytesIO
from fastapi import Request
from app.database import get_db
from app.utils.auth import get_current_user, require_mfa_verified, is_evaluator, get_token_payload, _payload_shows_mfa_verified
from app.utils.authz import has_role_db
from app.models.user import User
import logging, os
import hashlib
import logging
import os
from datetime import datetime
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from app.database import get_db
from app.utils.auth import get_current_user, require_mfa_verified
from app.models.user import User  # IMPORTANT: ORM model

router = APIRouter(prefix="/api", tags=["signature"])

SIGNATURE_DIR = "/var/www/k9sar_signatures"  # must match nginx alias folder
MAX_BYTES = 5 * 1024 * 1024  # 5MB


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

log = logging.getLogger("k9sar")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

from PIL import Image
import numpy as np

def clean_signature_image(im: Image.Image) -> Image.Image:
    im = im.convert("RGBA")
    arr = np.array(im).astype(np.float32)

    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3]

    brightness = (
        0.299 * rgb[:, :, 0] +
        0.587 * rgb[:, :, 1] +
        0.114 * rgb[:, :, 2]
    )

    # Very aggressive:
    # >= 210 becomes fully transparent
    # 150-210 gets faded
    # fully_bg = brightness >= 210
    # soft_bg = (brightness >= 150) & (brightness < 210)

    fully_bg = brightness >= 200
    soft_bg = (brightness >= 130) & (brightness < 200)
    fade = (200 - brightness[soft_bg]) / 40.0


    alpha[fully_bg] = 0

    # fade = (210 - brightness[soft_bg]) / 60.0
    # alpha[soft_bg] = alpha[soft_bg] * fade

    # Kill weak/semi-transparent remnants
    alpha[alpha < 160] = 0

    # Keep only strong ink
    alpha[alpha >= 160] = 255

    arr[:, :, 3] = np.clip(alpha, 0, 255)

    return Image.fromarray(arr.astype(np.uint8), "RGBA")

def analyze_signature_transparency(im: Image.Image) -> dict:
    im = im.convert("RGBA")
    arr = np.array(im)
    alpha = arr[:, :, 3]

    total = alpha.size
    transparent = (alpha < 20).sum()
    semi = ((alpha >= 20) & (alpha <= 220)).sum()
    opaque = (alpha > 220).sum()

    return {
        "transparent_pct": transparent / total,
        "semi_pct": semi / total,
        "opaque_pct": opaque / total,
    }


def crop_signature(im: Image.Image) -> Image.Image:
    arr = np.array(im)
    alpha = arr[:, :, 3]

    ys, xs = np.where(alpha > 20)

    if len(xs) == 0 or len(ys) == 0:
        return im

    pad = 12
    x_min = max(xs.min() - pad, 0)
    x_max = min(xs.max() + pad, im.width - 1)
    y_min = max(ys.min() - pad, 0)
    y_max = min(ys.max() + pad, im.height - 1)

    return im.crop((x_min, y_min, x_max + 1, y_max + 1))

@router.post("/me/signature")
def upload_my_signature(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    _mfa=Depends(require_mfa_verified),
):
    ct = (file.content_type or "").lower()
    if ct not in ("image/png", "image/jpeg", "image/jpg", "image/webp"):
        raise HTTPException(status_code=415, detail="Upload a PNG/JPEG/WEBP image.")

    raw = file.file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty upload.")
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 5MB).")

    try:
        im = Image.open(BytesIO(raw))
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGBA")
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read image.")

    uid = getattr(current_user, "user_id", None) or getattr(current_user, "id", None)
    if not uid:
        raise HTTPException(status_code=400, detail="Missing user id.")

    # Resize (optional)
    # Resize before cleanup
    MAX_W = 1400
    if im.width > MAX_W:
        new_h = int(im.height * (MAX_W / im.width))
        im = im.resize((MAX_W, new_h))

    # Auto-clean background and crop
    im = clean_signature_image(im)

    # Auto-clean background
    im = clean_signature_image(im)

    analysis = analyze_signature_transparency(im)
    log.info("signature analysis user_id=%s analysis=%s", uid, analysis)

    log.warning(
        "signature cleanup stats: transparent=%0.3f semi=%0.3f opaque=%0.3f",
        analysis["transparent_pct"],
        analysis["semi_pct"],
        analysis["opaque_pct"],
    )

    # 1. Must have enough ink
    if analysis["opaque_pct"] < 0.001:
        raise HTTPException(status_code=400, detail="The uploaded image does not contain a visible signature.")

    if analysis["semi_pct"] > 0.05:
        raise HTTPException(status_code=400, detail="The signature background is too noisy or uneven. Please upload a cleaner image.")

    if analysis["opaque_pct"] > 0.09:
        raise HTTPException(status_code=400, detail="The signature image contains too much dark artifacting. Please upload a cleaner signature.")

    # Crop AFTER validation
    im = crop_signature(im)
    im.thumbnail((600, 220))

    # os.makedirs(SIGNATURE_DIR, exist_ok=True)

    # filename = f"user_{uid}.png"
    # out_path = os.path.join(SIGNATURE_DIR, filename)

    # buf = BytesIO()
    # im.save(buf, format="PNG", optimize=True)
    # png_bytes = buf.getvalue()

    # # Write file
    # try:
    #     with open(out_path, "wb") as f:
    #         f.write(png_bytes)
    # except Exception as e:
    #     raise HTTPException(status_code=500, detail=f"Failed to write signature file: {e}")

    # # Verify write
    # if not os.path.exists(out_path) or os.path.getsize(out_path) <= 0:
    #     raise HTTPException(status_code=500, detail="Signature file write failed.")

    filename = f"user_{uid}.png"

    buf = BytesIO()
    im.save(buf, format="PNG", optimize=True)
    png_bytes = buf.getvalue()

    sig_hash = sha256_bytes(png_bytes)
    sig_url = f"/signatures/{filename}"
    now_utc_naive = datetime.utcnow()  # match your DB column (datetime)

    # IMPORTANT: update the session-bound ORM user
    user = db.query(User).filter(User.user_id == uid).one()
    user.signature_url = sig_url
    user.signature_hash = sig_hash
    user.signature_updated_at = now_utc_naive

    # Store current signature in DB too.
    # Keep the filesystem write for now to avoid changing existing behavior.
    db.execute(
        text("""
            UPDATE user_signatures
            SET is_active = 0
            WHERE user_id = :uid
            AND is_active = 1
        """),
        {"uid": uid},
    )

    db.execute(
        text("""
            INSERT INTO user_signatures
                (user_id, mime_type, image_data, sha256_hash, source_filename, uploaded_at, is_active)
            VALUES
                (:uid, 'image/png', :image_data, :sha256_hash, :source_filename, :uploaded_at, 1)
        """),
        {
            "uid": uid,
            "image_data": png_bytes,
            "sha256_hash": sig_hash,
            "source_filename": filename,
            "uploaded_at": now_utc_naive,
        },
    )

    db.commit()
    db.refresh(user)

    # log.info("signature updated user_id=%s path=%s size=%s", uid, out_path, os.path.getsize(out_path))
    log.info("signature updated user_id=%s db_bytes=%s", uid, len(png_bytes))

    return {
        "signature_url": user.signature_url,
        "signature_hash": user.signature_hash,
        "signature_updated_at": user.signature_updated_at,
    }


@router.get("/me/signature")
def get_my_signature(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    uid = getattr(current_user, "user_id", None) or getattr(current_user, "id", None)
    user = db.query(User).filter(User.user_id == uid).one()
    return {
        "signature_url": user.signature_url,
        "signature_hash": user.signature_hash,
        "signature_updated_at": user.signature_updated_at,
    }



@router.get("/me/signature/capabilities")
def signature_capabilities(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    payload: dict = Depends(get_token_payload),
):
    uid = current_user.user_id

    # Role gating (admin OR evaluator)
    is_admin = has_role_db(db, uid, "admin")
    is_eval = is_evaluator(db, uid)
    role_ok = is_admin or is_eval

    # MFA enabled on account?
    # MFA enabled on account? informational only
    mfa_enabled = bool(
        getattr(current_user, "mfa_enabled", False)
        or getattr(current_user, "twofa_enabled", False)
        or getattr(current_user, "is_mfa_enabled", False)
    )

    # MFA verified for THIS token/session
    mfa_verified = _payload_shows_mfa_verified(payload)

    # Policy: signatures require evaluator/admin role and an MFA-verified session
    allowed = role_ok and mfa_verified

    reason = None
    if not role_ok:
        reason = "Signature upload is only available to Evaluators and Admins."
    elif not mfa_verified:
        reason = "Please verify 2FA to upload/edit your signature."

    return {
        "allowed": allowed,
        "reason": reason,
        "role_ok": role_ok,
        "is_admin": is_admin,
        "is_evaluator": is_eval,
        "mfa_enabled": mfa_enabled,
        "mfa_verified": mfa_verified,
    }


@router.get("/signatures/{filename}")
def serve_signature(filename: str, db: Session = Depends(get_db)):
    match = re.match(r"^user_(\d+)\.png$", filename, re.IGNORECASE)
    if not match:
        raise HTTPException(status_code=404, detail="Signature not found")

    user_id = int(match.group(1))

    row = db.execute(
        text("""
            SELECT mime_type, image_data
            FROM user_signatures
            WHERE user_id = :user_id
              AND is_active = 1
            ORDER BY signature_id DESC
            LIMIT 1
        """),
        {"user_id": user_id},
    ).first()

    if row and row.image_data:
        return Response(
            content=row.image_data,
            media_type=row.mime_type or "image/png",
        )

    # Fallback to legacy file
    path = os.path.join(SIGNATURE_DIR, filename)
    if os.path.exists(path):
        return FileResponse(path, media_type="image/png")

    raise HTTPException(status_code=404, detail="Signature not found")

@router.get("/certificate-signatures/{certification_id}/{role}.png")
def serve_certificate_signature(
    certification_id: int,
    role: str,
    db: Session = Depends(get_db),
):
    if role not in ("supervisor", "co_evaluator"):
        raise HTTPException(status_code=404, detail="Signature not found")

    row = db.execute(
        text("""
            SELECT mime_type, image_data
            FROM certificate_signatures
            WHERE certification_id = :certification_id
              AND role = :role
            ORDER BY cert_signature_id DESC
            LIMIT 1
        """),
        {"certification_id": certification_id, "role": role},
    ).mappings().first()

    if not row or not row["image_data"]:
        raise HTTPException(status_code=404, detail="Signature not found")

    return Response(
        content=row["image_data"],
        media_type=row["mime_type"] or "image/png",
    )

