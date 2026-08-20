import os
from datetime import datetime, timedelta, timezone

from jose import jwt


FORUM_LINK_SECRET = os.getenv("FORUM_LINK_SECRET")
FORUM_LINK_ALGORITHM = "HS256"
FORUM_LINK_TTL_DAYS = 30


def create_forum_email_token(*, user_id: int, topic_id: int) -> str:
    if not FORUM_LINK_SECRET:
        raise RuntimeError("FORUM_LINK_SECRET is not configured")

    now = datetime.now(timezone.utc)

    payload = {
        "purpose": "forum_email_entry",
        "user_id": int(user_id),
        "topic_id": int(topic_id),
        "iat": now,
        "exp": now + timedelta(days=FORUM_LINK_TTL_DAYS),
    }

    return jwt.encode(
        payload,
        FORUM_LINK_SECRET,
        algorithm=FORUM_LINK_ALGORITHM,
    )