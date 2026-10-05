"""Text-only email replies. Reply addresses are short, expiring capabilities."""
import base64
import hashlib
import hmac
import os
import re
import struct
import time
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses

MAX_RAW_BYTES = 1024 * 1024
MAX_TEXT_BYTES = 20000
REPLY_MARKER = "--- Reply above this line to post to the forum ---"
TOKEN_PATTERN = re.compile(r"[a-z2-7]{45}", re.I)


def reply_config():
    secret = os.getenv("FORUM_REPLY_SECRET", "")
    webhook_secret = os.getenv("FORUM_INBOUND_SECRET", "")
    domain = os.getenv("FORUM_REPLY_DOMAIN", "").strip().lower()
    enabled = os.getenv("FORUM_EMAIL_REPLIES_ENABLED", "false").lower() == "true"
    if not enabled:
        return None
    if len(secret) < 32 or len(webhook_secret) < 32 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}", domain):
        raise RuntimeError("Forum email reply configuration is incomplete")
    return secret, webhook_secret, domain


def _signature(payload: bytes, email: str, secret: str) -> bytes:
    # Binding to the current address revokes tokens when a member changes email.
    data = b"forum-reply-v1\0" + payload + b"\0" + email.strip().lower().encode()
    return hmac.new(secret.encode(), data, hashlib.sha256).digest()[:16]


def create_reply_address(*, user_id: int, topic_id: int, email: str):
    config = reply_config()
    if config is None:
        return None
    secret, _, domain = config
    payload = struct.pack("!III", user_id, topic_id, int(time.time()) + 30 * 86400)
    token = base64.b32encode(payload + _signature(payload, email, secret)).decode().rstrip("=").lower()
    return f"forum+{token}@{domain}"


def decode_recipient(recipient: str, domain: str):
    local, sep, host = recipient.lower().rpartition("@")
    if not sep or host != domain or not local.startswith("forum+"):
        raise ValueError("Invalid forum reply address")
    token = local[6:]
    if not TOKEN_PATTERN.fullmatch(token):
        raise ValueError("Invalid forum reply address")
    raw = base64.b32decode(token.upper() + "===")
    if base64.b32encode(raw).decode().rstrip("=").lower() != token:
        raise ValueError("Invalid forum reply address")
    user_id, topic_id, expires = struct.unpack("!III", raw[:12])
    if expires <= time.time():
        raise ValueError("Reply address expired; open the forum to reply")
    return user_id, topic_id, raw


def verify_reply_token(raw: bytes, email: str, secret: str):
    if not hmac.compare_digest(raw[12:], _signature(raw[:12], email, secret)):
        raise ValueError("Invalid forum reply address")


def clean_reply(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    result = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Stop at quoted history, our marker, common Outlook headers or signatures.
        if (stripped == REPLY_MARKER or stripped.startswith(">")
                or stripped in ("--", "Sent from my iPhone", "Sent from my iPad", "Sent from my Android")
                or re.match(r"^-{2,}\s*(Original Message|Forwarded message)\s*-{2,}$", stripped, re.I)):
            break
        if re.match(r"^On\s+", stripped, re.I):
            wrapped = " ".join(part.strip() for part in lines[i:i + 5])
            if re.search(r"\bwrote:\s*(?:>|$)", wrapped, re.I) or re.search(r"\bwrote:$", stripped, re.I):
                break
        if re.match(r"^From:\s", stripped, re.I):
            following = "\n".join(lines[i + 1:i + 7])
            if re.search(r"^Sent:", following, re.I | re.M) and re.search(r"^Subject:", following, re.I | re.M):
                break
        result.append(line)
    reply = "\n".join(result).strip()
    if not reply:
        raise ValueError("No reply text found; write above the quoted message")
    if "\x00" in reply or len(reply.encode("utf-8")) > MAX_TEXT_BYTES:
        raise ValueError("Reply text exceeds the 20 KB limit or contains invalid characters")
    return reply


def parse_reply(raw: bytes, sender: str, expected_email: str):
    if len(raw) > MAX_RAW_BYTES:
        raise ValueError("Email exceeds the 1 MB limit")
    message = BytesParser(policy=policy.default).parsebytes(raw)
    if message.defects:
        raise ValueError("Malformed email")
    from_headers = message.get_all("From", [])
    addresses = getaddresses([str(value) for value in from_headers])
    if (len(from_headers) != 1 or len(addresses) != 1
            or addresses[0][1].lower() != expected_email.strip().lower()
            or sender.strip().lower() != expected_email.strip().lower()):
        raise ValueError("Reply from the email address registered to your member account")
    if (any(str(value).strip().lower() != "no" for value in message.get_all("Auto-Submitted", []))
            or message.get("List-Id")
            or any(str(value).strip().lower() in {"bulk", "junk", "list"} for value in message.get_all("Precedence", []))
            or message.get_content_type() == "multipart/report"):
        raise ValueError("Automated messages cannot post forum replies")
    # get_body skips attachments and nested message/rfc822 parts, and selects
    # text/plain from multipart/alternative. Never convert HTML or save files.
    part = message.get_body(preferencelist=("plain",))
    if part is None or part.get_content_type() != "text/plain" or part.get_filename():
        raise ValueError("Send a plain-text reply; HTML-only and attachment-only email is not supported")
    try:
        text = part.get_content()
    except (LookupError, UnicodeError):
        raise ValueError("Unsupported email text encoding") from None
    if part.defects:
        raise ValueError("Malformed email body")
    reply = clean_reply(text)
    ids = message.get_all("Message-ID", [])
    if len(ids) > 1:
        raise ValueError("Email contains multiple Message-ID headers")
    message_id = str(ids[0]).strip() if ids else ""
    if len(message_id) > 998:
        raise ValueError("Invalid Message-ID")
    identity = "id:" + message_id if message_id else "raw:" + hashlib.sha256(raw).hexdigest()
    return reply, identity
