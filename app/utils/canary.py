import os
from fastapi import Depends, HTTPException, Request

# Import your existing auth dependency
from app.utils.auth import get_current_user  # adjust path

def _parse_allowlist(value: str) -> set[int]:
    ids: set[int] = set()
    for part in (value or "").split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids

def canary_gate(
    request: Request,
    current_user=Depends(get_current_user),
):
    """
    Canary gate: deny access unless user_id is allowlisted.

    Safe properties:
    - cannot recurse (does not depend on anything that depends on canary)
    - never throws generic exceptions
    - fails with 401/403 only
    """

    # Feature flag off => allow everything
    if os.getenv("CANARY_MODE", "0") != "1":
        return

    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    allow_ids = _parse_allowlist(os.getenv("CANARY_ALLOW_USER_IDS", ""))

    # Optional: allow read-only endpoints even in canary mode
    # (handy to avoid breaking public pages/docs)
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return

    if current_user.user_id not in allow_ids:
        raise HTTPException(status_code=403, detail="Canary gate: access restricted")
