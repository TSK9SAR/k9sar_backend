"""Real ORM/route tests, with a database module isolated BEFORE app imports."""
import asyncio
import os
import sys
import types
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

# Never import the production database module (it runs create_all at import).
database = types.ModuleType("app.database")
database.Base = declarative_base()
database.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
database.SessionLocal = sessionmaker(bind=database.engine)
def get_db():
    with database.SessionLocal() as db:
        yield db
database.get_db = get_db
sys.modules["app.database"] = database

from fastapi import BackgroundTasks, HTTPException
from starlette.requests import Request
from app.models.forum import ForumCategory, ForumTopic, ForumPost, ForumEmailReceipt
from app.models.user import User
from app.models.role import Role
from app.models import handler_affiliations, email_campaigns  # register FK/relationship targets
from app.routes.forum_inbound_email import accept_reply, inbound_email
from app.services.forum_email_replies import create_reply_address
from app.services.forum_notifications import _send_forum_notifications
from test_forum_email_text import CONFIG, mail


class ReplyIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, CONFIG)
        self.env.start()
        # Only these tables are exercised; use production mappings, not fakes.
        self.tables = [User.__table__, Role.__table__, database.Base.metadata.tables["user_roles"],
                       ForumCategory.__table__, ForumTopic.__table__, ForumPost.__table__,
                       ForumEmailReceipt.__table__, database.Base.metadata.tables["forum_user_settings"]]
        database.Base.metadata.create_all(database.engine, tables=self.tables)
        self.db = database.SessionLocal()
        self.user = User(user_id=1, first_name="Test", last_name="Member", email="member@example.org",
                         username="member", password_hash="unused", is_active=True)
        self.author = User(user_id=2, first_name="Test", last_name="Author", email="author@example.org",
                           username="author", password_hash="unused", is_active=True)
        self.category = ForumCategory(category_id=1, name="Forum", slug="forum", min_role="member", notify_default="all")
        self.topic = ForumTopic(topic_id=1, category_id=1, title="Test", created_by_user_id=2)
        self.db.add_all([self.user, self.author, self.category, self.topic])
        self.db.commit()
        self.address = create_reply_address(user_id=1, topic_id=1, email=self.user.email)
        self.tasks = BackgroundTasks()

    def tearDown(self):
        self.db.close()
        database.Base.metadata.drop_all(database.engine, tables=list(reversed(self.tables)))
        self.env.stop()

    def accept(self, raw=None, **kwargs):
        return accept_reply(self.db, raw or mail().as_bytes(), kwargs.get("sender", self.user.email),
                            kwargs.get("recipient", self.address), CONFIG["FORUM_REPLY_SECRET"],
                            "tsk9sar.org", self.tasks)

    def test_posts_once_and_queues_standard_notification(self):
        first = self.accept()
        second = self.accept()
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["post_id"], second["post_id"])
        self.assertEqual(self.db.query(ForumPost).count(), 1)
        post = self.db.query(ForumPost).one()
        self.assertEqual((post.body_md, post.created_by_user_id, post.sort_order), ("Hello, team!", 1, 10))
        self.assertEqual(len(self.tasks.tasks), 1)
        self.assertEqual(self.tasks.tasks[0].kwargs["post_id"], post.post_id)

    def test_replay_does_not_restore_deleted_post(self):
        first = self.accept()
        self.db.delete(self.db.get(ForumPost, first["post_id"]))
        self.db.commit()
        self.assertTrue(self.accept()["duplicate"])
        self.assertEqual(self.db.query(ForumPost).count(), 0)

    def test_current_access_enforced(self):
        for obj, field, value in [(self.user, "is_active", False), (self.category, "is_active", False),
                                  (self.category, "min_role", "admin"), (self.topic, "is_locked", True)]:
            old = getattr(obj, field)
            setattr(obj, field, value)
            self.db.commit()
            with self.assertRaises(HTTPException):
                self.accept()
            setattr(obj, field, old)
            self.db.commit()
        self.assertEqual(self.db.query(ForumPost).count(), 0)

    def test_admin_lock_override_matches_website(self):
        self.user.roles.append(Role(role_name="admin"))
        self.topic.is_locked = True
        self.db.commit()
        self.assertFalse(self.accept()["duplicate"])

    def test_email_change_invalidates_address(self):
        self.user.email = "changed@example.org"
        self.db.commit()
        with self.assertRaises(HTTPException):
            self.accept(mail(sender="changed@example.org").as_bytes())

    def test_failed_receipt_commit_rolls_back_post(self):
        from sqlalchemy.exc import IntegrityError
        with patch.object(self.db, "commit", side_effect=IntegrityError("test", {}, Exception("failure"))):
            with self.assertRaises(IntegrityError):
                self.accept()
        self.assertEqual(self.db.query(ForumPost).count(), 0)
        self.assertEqual(len(self.tasks.tasks), 0)

    def test_notification_reply_to_flag_and_locked_topic(self):
        post = ForumPost(post_id=100, topic_id=1, body_md="Example", created_by_user_id=2)
        for enabled, locked, expected in [("false", False, False), ("true", False, True), ("true", True, False)]:
            self.topic.is_locked = locked
            with patch.dict(os.environ, {"FORUM_EMAIL_REPLIES_ENABLED": enabled}), \
                    patch("app.services.forum_notifications.create_forum_email_token", return_value="link-token"), \
                    patch("app.services.forum_notifications.send_email", return_value=True) as send:
                _send_forum_notifications(db=self.db, category=self.category, topic=self.topic, post=post,
                                          author=self.author, public_base_url="https://tsk9sar.org", kind="reply")
                args = send.call_args.kwargs
                self.assertEqual(bool(args["reply_to"]), expected)
                self.assertEqual("Only text is posted" in args["text_body"], expected)
                self.assertIn("/forums/email-entry/link-token", args["text_body"])

    def test_http_auth_limits_disabled_and_success(self):
        async def invoke(headers, body=b"", disabled=False):
            consumed = False
            async def receive():
                nonlocal consumed
                consumed = True
                return {"type": "http.request", "body": body, "more_body": False}
            request = Request({"type": "http", "method": "POST", "path": "/api/forums/inbound-email",
                               "headers": [(k.encode(), v.encode()) for k, v in headers.items()]}, receive)
            try:
                with patch.dict(os.environ, {"FORUM_EMAIL_REPLIES_ENABLED": "false" if disabled else "true"}):
                    result = await inbound_email(request, self.tasks, self.db)
                return 200, consumed, result
            except HTTPException as exc:
                return exc.status_code, consumed, None
        headers = {"authorization": "Bearer " + CONFIG["FORUM_INBOUND_SECRET"], "content-type": "message/rfc822",
                   "x-forum-envelope-from": self.user.email, "x-forum-envelope-to": self.address}
        self.assertEqual(asyncio.run(invoke({})), (401, False, None))
        self.assertEqual(asyncio.run(invoke(headers, disabled=True)), (503, False, None))
        self.assertEqual(asyncio.run(invoke({**headers, "content-type": "text/plain"})), (415, False, None))
        self.assertEqual(asyncio.run(invoke(headers, b"x" * 1048577))[0], 413)
        self.assertEqual(asyncio.run(invoke(headers, mail().as_bytes()))[0], 200)


if __name__ == "__main__":
    unittest.main()
