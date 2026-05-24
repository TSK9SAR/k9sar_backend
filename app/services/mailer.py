# app/services/mailer.py
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

def send_email(to_email: str, reply_to: str, subject: str, text_body: str, html_body: str | None = None) -> bool:
    host = (os.getenv("SMTP_HOST") or "").strip()
    port = int(os.getenv("SMTP_PORT") or "587")
    user = (os.getenv("SMTP_USER") or "").strip()
    password = os.getenv("SMTP_PASS") or ""
    from_email = (os.getenv("SMTP_FROM") or user).strip()

    use_tls = (os.getenv("SMTP_TLS", "true").strip().lower() in ("1", "true", "yes", "on"))
    use_ssl = (os.getenv("SMTP_SSL", "false").strip().lower() in ("1", "true", "yes", "on"))

    # # --- visible, non-sensitive diagnostics ---
    # print(f"[MAIL] host={host} port={port} tls={use_tls} ssl={use_ssl}", flush=True)
    # print(f"[MAIL] from={from_email} to={to_email} subject={subject}", flush=True)

    if not host:
        print("[MAIL] FAILED: SMTP_HOST is empty", flush=True)
        return False

    # Build message
    msg = MIMEMultipart("alternative")
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject

    if reply_to:
        msg["Reply-To"] = reply_to
        print(f"[MAIL] reply-to={reply_to}", flush=True)
    else:
        print("[MAIL] reply-to=(none)", flush=True)

    msg.attach(MIMEText(text_body or "", "plain", "utf-8"))
    if html_body:
        msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=20)
        else:
            server = smtplib.SMTP(host, port, timeout=20)

        # ✅ THIS is where it applies:
        # server.set_debuglevel(1)  # prints SMTP dialogue to stdout -> docker logs

        server.ehlo()
        if use_tls and not use_ssl:
            server.starttls()
            server.ehlo()

        if user and password:
            server.login(user, password)
        else:
            print("[MAIL] missing SMTP_USER/SMTP_PASS", flush=True)

        server.sendmail(from_email, [to_email], msg.as_string())
        server.quit()
        print("[MAIL] sent OK (SMTP accepted)", flush=True)
        return True

    except Exception as e:
        print(f"[MAIL] FAILED: {type(e).__name__}: {e}", flush=True)
        return False
