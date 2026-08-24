# app/services/mailer.py

import os
import smtplib
import mimetypes

from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TypedDict


class MailAttachment(TypedDict):
    path: str
    filename: str
    mime_type: str | None


def send_email(
    to_email: str,
    reply_to: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
    attachments: list[MailAttachment] | None = None,
) -> bool:

    host = (os.getenv("SMTP_HOST") or "").strip()
    port = int(os.getenv("SMTP_PORT") or "587")
    user = (os.getenv("SMTP_USER") or "").strip()
    password = os.getenv("SMTP_PASS") or ""
    from_email = (os.getenv("SMTP_FROM") or user).strip()

    use_tls = (
        os.getenv("SMTP_TLS", "true")
        .strip()
        .lower()
        in ("1", "true", "yes", "on")
    )

    use_ssl = (
        os.getenv("SMTP_SSL", "false")
        .strip()
        .lower()
        in ("1", "true", "yes", "on")
    )

    if not host:
        print(
            "[MAIL] FAILED: SMTP_HOST is empty",
            flush=True,
        )
        return False

    #
    # Outer container:
    # text/html body + optional file attachments.
    #
    msg = MIMEMultipart("mixed")

    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject

    if reply_to:
        msg["Reply-To"] = reply_to
        print(
            f"[MAIL] reply-to={reply_to}",
            flush=True,
        )
    else:
        print(
            "[MAIL] reply-to=(none)",
            flush=True,
        )

    #
    # Inner body container.
    #
    body = MIMEMultipart("alternative")

    body.attach(
        MIMEText(
            text_body or "",
            "plain",
            "utf-8",
        )
    )

    if html_body:
        body.attach(
            MIMEText(
                html_body,
                "html",
                "utf-8",
            )
        )

    msg.attach(body)

    #
    # File attachments.
    #
    for attachment in attachments or []:

        path = attachment["path"]
        filename = attachment["filename"]
        mime_type = attachment.get("mime_type")

        if not mime_type:
            mime_type, _ = mimetypes.guess_type(
                filename
            )

        if (
            mime_type
            and "/" in mime_type
        ):
            maintype, subtype = mime_type.split(
                "/",
                1,
            )
        else:
            maintype = "application"
            subtype = "octet-stream"

        with open(path, "rb") as file_handle:
            part = MIMEBase(
                maintype,
                subtype,
            )

            part.set_payload(
                file_handle.read()
            )

        encoders.encode_base64(part)

        part.add_header(
            "Content-Disposition",
            "attachment",
            filename=filename,
        )

        msg.attach(part)

    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(
                host,
                port,
                timeout=20,
            )
        else:
            server = smtplib.SMTP(
                host,
                port,
                timeout=20,
            )

        server.ehlo()

        if use_tls and not use_ssl:
            server.starttls()
            server.ehlo()

        if user and password:
            server.login(
                user,
                password,
            )
        else:
            print(
                "[MAIL] missing SMTP_USER/SMTP_PASS",
                flush=True,
            )

        server.sendmail(
            from_email,
            [to_email],
            msg.as_string(),
        )

        server.quit()

        print(
            "[MAIL] sent OK (SMTP accepted)",
            flush=True,
        )

        return True

    except Exception as e:
        print(
            f"[MAIL] FAILED: "
            f"{type(e).__name__}: {e}",
            flush=True,
        )

        return False