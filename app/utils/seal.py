# seal.py
from __future__ import annotations

import hashlib
from datetime import datetime, date
from typing import Any, Optional

from sqlalchemy import text


def _norm(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.replace(microsecond=0).isoformat(sep="T")
    if isinstance(v, date):
        return v.isoformat()
    return str(v).strip()


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def build_seal_payload_v2(*, cert: Any) -> str:
    parts = [
        "v2",
        f"certification_id={_norm(getattr(cert, 'certification_id', None))}",
        f"team_id={_norm(getattr(cert, 'team_id', None))}",
        f"standard_id={_norm(getattr(cert, 'standard_id', None))}",
        f"date_awarded={_norm(getattr(cert, 'date_awarded', None))}",
        f"expires_at={_norm(getattr(cert, 'expires_at', None))}",
        f"location={_norm(getattr(cert, 'location', None))}",
        f"supervisor_id={_norm(getattr(cert, 'supervisor_id', None))}",
        f"issued_at={_norm(getattr(cert, 'issued_at', None))}",
    ]
    return "|".join(parts)


def get_certificate_signature_hashes(db, certification_id: int) -> dict[str, str]:
    if db is None:
        return {
            "supervisor_signature_hash": "",
            "co_evaluator_signature_hash": "",
        }

    rows = db.execute(
        text("""
            SELECT role, sha256_hash
            FROM certificate_signatures
            WHERE certification_id = :certification_id
        """),
        {"certification_id": certification_id},
    ).mappings().all()

    out = {
        "supervisor_signature_hash": "",
        "co_evaluator_signature_hash": "",
    }

    for r in rows:
        if r["role"] == "supervisor":
            out["supervisor_signature_hash"] = r["sha256_hash"] or ""
        elif r["role"] == "co_evaluator":
            out["co_evaluator_signature_hash"] = r["sha256_hash"] or ""

    return out


def build_seal_payload_v3(*, cert: Any, db) -> str:
    sig_hashes = get_certificate_signature_hashes(
        db,
        int(getattr(cert, "certification_id", 0) or 0),
    )

    parts = [
        "v3",
        f"certification_id={_norm(getattr(cert, 'certification_id', None))}",
        f"team_id={_norm(getattr(cert, 'team_id', None))}",
        f"standard_id={_norm(getattr(cert, 'standard_id', None))}",
        f"date_awarded={_norm(getattr(cert, 'date_awarded', None))}",
        f"expires_at={_norm(getattr(cert, 'expires_at', None))}",
        f"location={_norm(getattr(cert, 'location', None))}",
        f"supervisor_id={_norm(getattr(cert, 'supervisor_id', None))}",
        f"issued_at={_norm(getattr(cert, 'issued_at', None))}",
        f"supervisor_signature_hash={_norm(sig_hashes['supervisor_signature_hash'])}",
        f"co_evaluator_user_id={_norm(getattr(cert, 'co_evaluator_user_id', None))}",
        f"co_evaluator_signature_hash={_norm(sig_hashes['co_evaluator_signature_hash'])}",
    ]
    return "|".join(parts)


def compute_seal_hash(*, cert: Any, db=None) -> str:
    v = int(getattr(cert, "seal_version", None) or 1)

    if v == 3:
        return sha256_hex(build_seal_payload_v3(cert=cert, db=db))

    if v == 2:
        return sha256_hex(build_seal_payload_v2(cert=cert))

    return compute_seal_hash_v1(cert=cert)


def compute_seal_hash_v1(*, cert: Any) -> str:
    payload = build_seal_payload_v2(cert=cert)
    return sha256_hex(payload)


def short_code(seal_hash: Optional[str]) -> str:
    if not seal_hash:
        return ""
    s = seal_hash[:12].upper()
    return f"{s[0:4]}-{s[4:8]}-{s[8:12]}"