# app/services/links.py
import os
from urllib.parse import urlencode, quote

PUBLIC_BASE_URL = os.environ["PUBLIC_BASE_URL"].rstrip("/")
# or, if you want a fallback:
# PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://k9sar.roamer105.com").rstrip("/")

FRONTEND_BASENAME = os.getenv("FRONTEND_BASENAME", "/app")  # keep leading slash

def frontend_url(path: str, **query) -> str:
    """
    Build an absolute frontend URL for links in emails.
    Ensures paths are under the SPA basename (default /app).
    """
    p = path if path.startswith("/") else f"/{path}"
    base = FRONTEND_BASENAME if FRONTEND_BASENAME.startswith("/") else f"/{FRONTEND_BASENAME}"

    url = f"{PUBLIC_BASE_URL}{base}{p}"
    if query:
        # Use quote (not quote_plus) so spaces encode as %20 instead of +
        url += "?" + urlencode(
            {k: v for k, v in query.items() if v is not None},
            quote_via=quote,
        )
    return url
# 