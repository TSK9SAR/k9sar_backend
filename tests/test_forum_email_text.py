import os
import time
import unittest
from email.message import EmailMessage
from unittest.mock import patch
from app.services.forum_email_replies import (
    REPLY_MARKER, clean_reply, create_reply_address, decode_recipient,
    parse_reply, verify_reply_token,
)

CONFIG = {"FORUM_EMAIL_REPLIES_ENABLED": "true", "FORUM_REPLY_DOMAIN": "tsk9sar.org",
          "FORUM_REPLY_SECRET": "reply-test-secret-" * 3, "FORUM_INBOUND_SECRET": "ingress-test-secret-" * 3}


def mail(text="Hello, team!", sender="member@example.org", message_id="<reply-1@example.org>"):
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "forum@example.org"
    if message_id:
        msg["Message-ID"] = message_id
    msg.set_content(text)
    return msg


class ReplyTextTests(unittest.TestCase):
    def test_capability_bound_to_user_topic_email_and_expiry(self):
        with patch.dict(os.environ, CONFIG):
            address = create_reply_address(user_id=7, topic_id=12, email="member@example.org")
            self.assertLessEqual(len(address.split("@")[0]), 64)
            uid, tid, raw = decode_recipient(address, "tsk9sar.org")
            self.assertEqual((uid, tid), (7, 12))
            verify_reply_token(raw, "member@example.org", CONFIG["FORUM_REPLY_SECRET"])
            for email, secret in [("other@example.org", CONFIG["FORUM_REPLY_SECRET"]), ("member@example.org", "changed")]:
                with self.assertRaises(ValueError):
                    verify_reply_token(raw, email, secret)
            with patch("time.time", return_value=time.time() + 31 * 86400):
                with self.assertRaises(ValueError):
                    decode_recipient(address, "tsk9sar.org")
            with self.assertRaises(ValueError):
                decode_recipient(address, "wrong.org")

    def test_feature_off_preserves_existing_notifications(self):
        with patch.dict(os.environ, {"FORUM_EMAIL_REPLIES_ENABLED": "false"}):
            self.assertIsNone(create_reply_address(user_id=1, topic_id=1, email="member@example.org"))

    def test_common_quote_formats(self):
        for quote in ["> Old text", REPLY_MARKER + "\nold text", "On Sunday, Sam wrote:\n> old text",
                      "On Sunday, a very long sender\nname wrote:\n> old text",
                      "-----Original Message-----\nold text", "From: Sam\nSent: Sunday\nTo: Team\nSubject: Old\nold text",
                      "-- \nSam", "Sent from my iPhone"]:
            with self.subTest(quote=quote):
                self.assertEqual(clean_reply("New answer\n\n" + quote), "New answer")

    def test_unicode_and_encoded_text(self):
        for cte in ("quoted-printable", "base64"):
            msg = mail()
            msg.set_content("Grüezi 🐕", cte=cte)
            self.assertEqual(parse_reply(msg.as_bytes(), "member@example.org", "member@example.org")[0], "Grüezi 🐕")

    def test_multipart_selects_text_and_ignores_attachments(self):
        msg = mail("My reply\n\n> old discussion")
        msg.add_alternative("<p>Untrusted HTML</p>", subtype="html")
        msg.add_attachment(b"not forum text", maintype="application", subtype="octet-stream", filename="file.bin")
        msg.add_attachment(mail("attached message must not post"))
        self.assertEqual(parse_reply(msg.as_bytes(), "member@example.org", "member@example.org")[0], "My reply")

    def test_html_or_attachment_only_rejected(self):
        html = mail()
        html.set_content("<p>Hello</p>", subtype="html")
        attachment = mail()
        attachment["Content-Disposition"] = 'attachment; filename="reply.txt"'
        nested = EmailMessage()
        nested["From"] = "member@example.org"
        nested.add_attachment(mail())
        for msg in (html, attachment, nested):
            with self.assertRaises(ValueError):
                parse_reply(msg.as_bytes(), "member@example.org", "member@example.org")

    def test_wrong_sender_automated_mail_and_empty_rejected(self):
        for header, value in [("Auto-Submitted", "auto-replied"), ("Precedence", "bulk"), ("List-Id", "mailing-list")]:
            msg = mail()
            msg[header] = value
            with self.assertRaises(ValueError):
                parse_reply(msg.as_bytes(), "member@example.org", "member@example.org")
        for sender, expected in [("spoof@example.org", "member@example.org"), ("member@example.org", "other@example.org")]:
            with self.assertRaises(ValueError):
                parse_reply(mail().as_bytes(), sender, expected)
        for body in ("   ", "> Only quoted text", "a" * 20001, "x\x00y"):
            with self.assertRaises(ValueError):
                parse_reply(mail(body).as_bytes(), "member@example.org", "member@example.org")

    def test_message_identity_stable_across_transport_headers(self):
        msg = mail()
        first = parse_reply(msg.as_bytes(), "member@example.org", "member@example.org")[1]
        msg["Received"] = "another delivery hop"
        self.assertEqual(first, parse_reply(msg.as_bytes(), "member@example.org", "member@example.org")[1])
        raw = mail(message_id=None).as_bytes()
        self.assertEqual(parse_reply(raw, "member@example.org", "member@example.org")[1],
                         parse_reply(raw, "member@example.org", "member@example.org")[1])


if __name__ == "__main__":
    unittest.main()
