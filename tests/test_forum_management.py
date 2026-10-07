"""HTTP/ORM regressions in SQLite; never import app.main or the production database.

Run: python -m unittest discover -s tests -p 'test_forum_management.py' -v
"""
import asyncio
from datetime import datetime
import json
import os
import unittest
from unittest.mock import patch

# Reuse the email suite's database isolation BEFORE importing authenticated routes.
import test_forum_email_integration as email_tests
from fastapi import FastAPI, HTTPException
from app.models.forum import (ForumCategory, ForumTopic, ForumPost, ForumBallot,
                              ForumBallotChoice, ForumBallotVote, ForumBallotFeedback,
                              ForumTopicRead, ForumEmailReceipt)
from app.models.stored_files import StoredFile, ForumPostAttachment
from app.models.role import Role
from app.routes import admin_forum_management as management
from app.services import forum_notifications as notifications
from app.utils.auth import get_current_user, get_jwt_claims

database = email_tests.database


class ForumManagementTests(unittest.TestCase):
    def setUp(self):
        email_tests.ReplyIntegrationTests.setUp(self)
        self.signing = patch.dict(os.environ, {"JWT_SECRET": "isolated-management-test-secret"})
        self.signing.start()
        extra = [ForumBallot.__table__, ForumBallotChoice.__table__, ForumBallotVote.__table__,
                 ForumBallotFeedback.__table__, ForumTopicRead.__table__, StoredFile.__table__, ForumPostAttachment.__table__]
        database.Base.metadata.create_all(database.engine, tables=extra)
        self.tables.extend(extra)
        self.user.roles.append(Role(role_id=3, role_name="admin"))
        self.destination = ForumCategory(category_id=2, name="Private", slug="private", min_role="admin", notify_default="none")
        self.hidden = ForumCategory(category_id=3, name="Hidden", slug="hidden", is_active=False)
        self.db.add_all([self.destination, self.hidden])
        self.db.commit()
        self.current_user = self.user
        self.claims = {"typ": "access", "mfa_verified": True, "mfa_method": "totp"}
        self.app = FastAPI()
        self.app.include_router(management.router, prefix="/api")
        self.app.dependency_overrides[get_current_user] = lambda: self.current_user
        self.app.dependency_overrides[get_jwt_claims] = lambda: self.claims

    def tearDown(self):
        self.signing.stop()
        email_tests.ReplyIntegrationTests.tearDown(self)

    def request(self, method, path, body=None):
        async def invoke():
            messages = []
            raw = json.dumps(body).encode() if body is not None else b""
            async def receive():
                return {"type": "http.request", "body": raw, "more_body": False}
            async def send(message):
                messages.append(message)
            route, _, query = path.partition("?")
            await self.app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                            "method": method, "scheme": "http", "path": "/api/admin/forum" + route,
                            "raw_path": ("/api/admin/forum" + route).encode(), "query_string": query.encode(),
                            "headers": [(b"content-type", b"application/json")], "server": ("test", 80),
                            "client": ("127.0.0.1", 1234), "root_path": ""}, receive, send)
            status = next(message["status"] for message in messages if message["type"] == "http.response.start")
            data = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
            self.db.expire_all()
            return status, json.loads(data) if data else None
        return asyncio.run(invoke())

    def preview_move(self, topic=1, destination=2):
        status, data = self.request("POST", f"/topics/{topic}/move-preview", {"destination_category_id": destination})
        self.assertEqual(status, 200, data)
        return data

    def confirm_move(self, preview, destination=2):
        return self.request("POST", "/topics/1/move-confirm", {"destination_category_id": destination, "confirmation_token": preview["confirmation_token"]})

    def test_all_routes_require_admin_and_mutations_require_mfa(self):
        routes = [("GET", "/categories", None), ("GET", "/topics", None),
                  ("POST", "/categories", {"name": "New"}),
                  ("PUT", "/categories/1", {"name": "Changed", "expected_revision": "x" * 64}),
                  ("POST", "/categories/2/delete-preview", None),
                  ("POST", "/categories/2/delete-confirm", {"confirmation_token": "invalid", "confirm_text": "DELETE Private"}),
                  ("POST", "/topics/1/move-preview", {"destination_category_id": 2}),
                  ("POST", "/topics/1/move-confirm", {"destination_category_id": 2, "confirmation_token": "invalid"})]
        for role in [None, Role(role_id=2, role_name="supervisor")]:
            if role:
                self.author.roles.append(role)
                self.db.commit()
            self.current_user = self.author
            for method, route, body in routes:
                with self.subTest(role=getattr(role, "role_name", "member"), route=route):
                    self.assertEqual(self.request(method, route, body)[0], 403)
        self.current_user = self.user
        self.claims = {"typ": "access", "mfa_verified": False}
        for method, route, body in routes:
            self.assertEqual(self.request(method, route, body)[0], 200 if method == "GET" else 403)
        del self.app.dependency_overrides[get_current_user]
        for method, route, body in routes:
            self.assertEqual(self.request(method, route, body)[0], 401)

    def test_category_create_edit_hide_restore_and_stale_edit(self):
        status, created = self.request("POST", "/categories", {"name": "  Training  ", "description": "Practice", "sortorder": -2})
        self.assertEqual(status, 201, created)
        self.assertEqual(created["name"], "Training")
        category_id = created["category_id"]
        old_slug = self.db.get(ForumCategory, category_id).slug
        payload = {"name": "Training & Exercises", "is_active": False, "min_role": "supervisor", "notify_default": "announcements", "sortorder": -3, "expected_revision": created["revision"]}
        status, hidden = self.request("PUT", f"/categories/{category_id}", payload)
        self.assertEqual(status, 200, hidden)
        self.assertFalse(hidden["is_active"])
        self.assertEqual(self.db.get(ForumCategory, category_id).slug, old_slug)
        self.assertEqual(self.request("PUT", f"/categories/{category_id}", payload)[0], 409)
        payload.update(is_active=True, expected_revision=hidden["revision"])
        self.assertEqual(self.request("PUT", f"/categories/{category_id}", payload)[0], 200)
        status, categories = self.request("GET", "/categories")
        self.assertEqual(categories[0]["category_id"], category_id)
        self.assertEqual(next(c for c in categories if c["category_id"] == 1)["topic_count"], 1)
        self.assertTrue(any(not c["is_active"] for c in categories))

    def test_category_validation_and_duplicate_slugs(self):
        for payload in [{"name": "  "}, {"name": "x" * 121}, {"name": "ok", "min_role": "anyone"},
                        {"name": "ok", "notify_default": "spam"}, {"name": "ok", "sortorder": 100001},
                        {"name": "ok", "is_active": "false"}, {"name": "ok", "slug": "unsafe"}]:
            self.assertEqual(self.request("POST", "/categories", payload)[0], 422)
        for _ in range(2):
            self.assertEqual(self.request("POST", "/categories", {"name": "Forum"})[0], 201)
        self.assertEqual(self.db.query(ForumCategory.slug).distinct().count(), 5)

    def test_delete_requires_empty_category_and_matching_review(self):
        self.assertEqual(self.request("POST", "/categories/1/delete-preview")[0], 409)
        _, preview = self.request("POST", "/categories/2/delete-preview")
        body = {"confirmation_token": preview["confirmation_token"], "confirm_text": "wrong"}
        self.assertEqual(self.request("POST", "/categories/2/delete-confirm", body)[0], 400)
        body["confirm_text"] = preview["confirm_text"]
        self.destination.name = "Renamed"
        self.db.commit()
        self.assertEqual(self.request("POST", "/categories/2/delete-confirm", body)[0], 409)
        _, preview = self.request("POST", "/categories/2/delete-preview")
        body = {"confirmation_token": preview["confirmation_token"], "confirm_text": preview["confirm_text"]}
        self.assertEqual(self.request("POST", "/categories/2/delete-confirm", body)[0], 200)
        self.assertIsNone(self.db.get(ForumCategory, 2))
        self.assertIsNotNone(self.db.get(ForumTopic, 1))

    def test_delete_rechecks_topics_added_after_preview(self):
        _, preview = self.request("POST", "/categories/2/delete-preview")
        self.db.add(ForumTopic(topic_id=2, category_id=2, title="New topic", created_by_user_id=2))
        self.db.commit()
        status, _ = self.request("POST", "/categories/2/delete-confirm", {"confirmation_token": preview["confirmation_token"], "confirm_text": preview["confirm_text"]})
        self.assertEqual(status, 409)
        self.assertIsNotNone(self.db.get(ForumCategory, 2))

    def test_move_preserves_entire_discussion_and_does_not_send_mail(self):
        self.topic.is_locked = self.topic.is_pinned = True
        self.db.add_all([
            ForumPost(post_id=7, topic_id=1, body_md="Opening", created_by_user_id=2),
            ForumPost(post_id=8, topic_id=1, body_md="Removed", created_by_user_id=2, deleted_at=datetime(2026, 1, 1)),
            ForumBallot(ballot_id=1, topic_id=1, post_id=7, title="Poll", ballot_type="single_choice", created_by_user_id=2),
            ForumBallotChoice(choice_id=1, ballot_id=1, label="Yes"),
            ForumBallotVote(vote_id=1, ballot_id=1, choice_id=1, user_id=2),
            ForumBallotFeedback(feedback_id=1, ballot_id=1, choice_id=1, user_id=2, feedback_text="Good"),
            ForumTopicRead(user_id=2, topic_id=1, last_read_at=datetime(2026, 1, 1)),
            ForumEmailReceipt(delivery_key="x" * 64, post_id=7),
            StoredFile(file_id=1, original_filename="example.txt", stored_filename="test.txt", mime_type="text/plain", file_size=3, sha256_hash="a" * 64, storage_path="test.txt", uploaded_by_user_id=2),
            ForumPostAttachment(attachment_id=1, post_id=7, file_id=1),
        ])
        self.db.commit()
        last_post_at = self.topic.last_post_at
        preserved = [ForumPost, ForumBallot, ForumBallotChoice, ForumBallotVote, ForumBallotFeedback, ForumTopicRead, ForumEmailReceipt, StoredFile, ForumPostAttachment]
        def snapshot():
            return {model.__tablename__: [tuple(getattr(row, col.name) for col in model.__table__.columns) for row in self.db.query(model).all()] for model in preserved}
        before = snapshot()
        preview = self.preview_move()
        self.assertEqual((preview["post_count"], preview["poll_count"], preview["attachment_count"]), (2, 1, 1))
        with patch.object(notifications, "send_email") as send:
            self.assertEqual(self.confirm_move(preview)[0], 200)
            send.assert_not_called()
        self.assertEqual(snapshot(), before)
        self.assertEqual((self.topic.category_id, self.topic.is_locked, self.topic.is_pinned, self.topic.last_post_at), (2, True, True, last_post_at))

    def test_move_confirmation_expiry_tampering_user_binding_and_changed_permissions(self):
        preview = self.preview_move()
        tampered = {**preview, "confirmation_token": preview["confirmation_token"][:-1] + "z"}
        self.assertEqual(self.confirm_move(tampered)[0], 409)
        unicode_token = {**preview, "confirmation_token": str(preview["expires_at"]) + ".é"}
        self.assertEqual(self.confirm_move(unicode_token)[0], 409)
        with patch.object(management.time, "time", return_value=preview["expires_at"] + 1):
            self.assertEqual(self.confirm_move(preview)[0], 409)
        self.author.roles.append(self.db.get(Role, 3)); self.db.commit()
        self.current_user = self.author
        self.assertEqual(self.confirm_move(preview)[0], 409)
        self.current_user = self.user
        self.destination.min_role = "member"; self.db.commit()
        self.assertEqual(self.confirm_move(preview)[0], 409)
        self.assertEqual(self.topic.category_id, 1)

    def test_move_rejects_missing_same_or_hidden_destination_and_stale_source(self):
        for destination, expected in [(1, 400), (3, 409), (999, 404)]:
            self.assertEqual(self.request("POST", "/topics/1/move-preview", {"destination_category_id": destination})[0], expected)
        self.assertEqual(self.request("POST", "/topics/999/move-preview", {"destination_category_id": 2})[0], 404)
        preview = self.preview_move()
        self.topic.category_id = 3; self.db.commit()
        self.assertEqual(self.confirm_move(preview)[0], 409)
        # Administrators can rescue topics from hidden categories.
        preview = self.preview_move()
        self.assertFalse(preview["source"]["is_active"])
        self.assertEqual(self.confirm_move(preview)[0], 200)

    def test_topic_search_filter_and_pagination_include_hidden_categories(self):
        self.db.add_all([ForumTopic(topic_id=2, category_id=3, title="Hidden exercise", created_by_user_id=2),
                         ForumTopic(topic_id=3, category_id=1, title="100% attendance", created_by_user_id=2)])
        self.db.commit()
        _, data = self.request("GET", "/topics?q=%25")
        self.assertEqual([t["topic_id"] for t in data["items"]], [3])
        _, data = self.request("GET", "/topics?category_id=3")
        self.assertEqual(data["total"], 1); self.assertFalse(data["items"][0]["category_active"])
        _, data = self.request("GET", "/topics?limit=1&offset=1")
        self.assertEqual(data["total"], 3); self.assertEqual(len(data["items"]), 1)
        _, data = self.request("GET", "/topics?topic_id=1")
        self.assertEqual([t["topic_id"] for t in data["items"]], [1])

    def test_old_email_reply_address_uses_new_category_access(self):
        self.assertEqual(self.confirm_move(self.preview_move())[0], 200)
        # Original recipient loses administrator role, and old reply address is denied.
        self.user.roles.clear(); self.db.commit()
        with self.assertRaises(HTTPException) as caught:
            email_tests.ReplyIntegrationTests.accept(self)
        self.assertEqual(caught.exception.status_code, 403)
        self.destination.min_role = "member"; self.db.commit()
        self.assertFalse(email_tests.ReplyIntegrationTests.accept(self)["duplicate"])

    def test_queued_notifications_use_destination_and_skip_hidden_categories(self):
        self.db.add(ForumPost(post_id=1, topic_id=1, body_md="Hello", created_by_user_id=2))
        self.db.commit()
        self.assertEqual(self.confirm_move(self.preview_move())[0], 200)
        for job in [notifications.send_new_topic_notifications, notifications.send_new_reply_notifications]:
            with patch.object(notifications, "_send_forum_notifications") as send:
                job(category_id=1, topic_id=1, post_id=1, author_user_id=2, public_base_url="https://example.org")
                self.assertEqual(send.call_args.kwargs["category"].category_id, 2)
        self.destination.is_active = False; self.db.commit()
        with patch.object(notifications, "send_email") as send:
            notifications.send_new_reply_notifications(category_id=1, topic_id=1, post_id=1, author_user_id=2, public_base_url="https://example.org")
            send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
