"""Invitation history HTTP/ORM tests with SQLite installed before app imports."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
import unittest
from unittest.mock import patch

# Reuse the existing isolation bootstrap; never import the production database.
import test_forum_email_integration as isolated
from fastapi import FastAPI
from app.models.user import User
from app.models.role import Role
from app.models.user_invite import UserInvite
from app.routes import admin_invites
with patch.dict(os.environ, {"PUBLIC_BASE_URL": "https://example.invalid"}):
    from app.routes.invite_routes import verify_invite
from app.services.tokens import token_hash
from app.utils.auth import get_current_user

database = isolated.database
NOW = datetime(2026, 10, 12, 18, 0, tzinfo=timezone.utc)


class InvitationHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tables = [User.__table__, Role.__table__, database.Base.metadata.tables["user_roles"], UserInvite.__table__]
        database.Base.metadata.create_all(database.engine, tables=self.tables)
        self.db = database.SessionLocal()
        self.admin = User(user_id=1, username="admin", email="admin@example.invalid", first_name="Test", last_name="Admin", password_hash="unused", is_active=True)
        self.supervisor = User(user_id=2, username="supervisor", email="supervisor@example.invalid", first_name="Test", last_name="Supervisor", password_hash="unused", is_active=True)
        self.member = User(user_id=3, username="member", email="member@example.invalid", first_name="", last_name="", password_hash="unused", is_active=True)
        self.admin.roles.append(Role(role_id=3, role_name="admin"))
        self.supervisor.roles.append(Role(role_id=2, role_name="supervisor"))
        self.member.roles.append(Role(role_id=1, role_name="member"))
        self.db.add_all([self.admin, self.supervisor, self.member])
        self.db.commit()
        self.add_invite(1, "pending", first_name="Casey", last_name="Smith", email="casey@example.invalid")
        self.add_invite(2, "completed", first_name="Jordan", last_name="Lee")
        self.add_invite(3, "expired", first_name="Robin", last_name="Lee")
        self.current_user = self.admin
        self.app = FastAPI()
        self.app.include_router(admin_invites.router, prefix="/api")
        self.app.dependency_overrides[get_current_user] = lambda: self.current_user
        self.clock = patch.object(admin_invites, "_utcnow", return_value=NOW)
        self.clock.start()

    def tearDown(self):
        self.clock.stop()
        self.db.close()
        database.Base.metadata.drop_all(database.engine, tables=list(reversed(self.tables)))

    def add_invite(self, invite_id, status, **overrides):
        now = NOW.replace(tzinfo=None)
        fields = dict(invite_id=invite_id, email=f"invite{invite_id}@example.invalid", first_name="Example", last_name="Invitee",
                      phone="PRIVATE-PHONE", role_ids_json="[1]", token_hash=token_hash(f"test-token-{invite_id}"),
                      created_at=now - timedelta(days=invite_id), expires_at=now + timedelta(days=2, hours=3),
                      created_by_user_id=1, used_at=None)
        if status == "completed":
            fields.update(used_at=now - timedelta(days=1), user_id=3, expires_at=now - timedelta(hours=1))
        elif status == "expired":
            fields["expires_at"] = now - timedelta(seconds=1)
        fields.update(overrides)
        row = UserInvite(**fields)
        self.db.add(row)
        self.db.commit()
        return row

    def request(self, query=""):
        async def invoke():
            messages = []
            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}
            async def send(message):
                messages.append(message)
            await self.app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
                            "scheme": "http", "path": "/api/admin/invites", "raw_path": b"/api/admin/invites",
                            "query_string": query.encode(), "headers": [], "server": ("test", 80), "client": ("127.0.0.1", 1234), "root_path": ""}, receive, send)
            start = next(message for message in messages if message["type"] == "http.response.start")
            body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
            return start["status"], json.loads(body), dict(start["headers"])
        return asyncio.run(invoke())

    def test_history_requires_administrator(self):
        for user in [self.member, self.supervisor]:
            self.current_user = user
            self.assertEqual(self.request()[0], 403)
        del self.app.dependency_overrides[get_current_user]
        self.assertEqual(self.request()[0], 401)

    def test_status_counts_and_utc_dates(self):
        status, data, headers = self.request()
        self.assertEqual(status, 200, data)
        self.assertEqual(headers[b"cache-control"], b"no-store")
        self.assertEqual(data["counts"], {"all": 3, "pending": 1, "completed": 1, "expired": 1})
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["evaluated_at"], "2026-10-12T18:00:00Z")
        pending, completed, expired = data["items"]
        self.assertEqual([item["status"] for item in data["items"]], ["pending", "completed", "expired"])
        self.assertEqual(pending["remaining_seconds"], (2 * 24 + 3) * 3600)
        self.assertEqual(completed["remaining_seconds"], 0)
        self.assertEqual(expired["remaining_seconds"], 0)
        self.assertEqual(completed["completed_at"], "2026-10-11T18:00:00Z")
        self.assertEqual(pending["created_by_name"], "Test Admin")
        for row in data["items"]:
            self.assertTrue(row["expires_at"].endswith("Z"))

    def test_filters_match_counts_and_keep_completed_after_expiry(self):
        for status_filter, invite_id in [("pending", 1), ("completed", 2), ("expired", 3)]:
            code, data, _ = self.request(f"status={status_filter}")
            self.assertEqual(code, 200)
            self.assertEqual(data["total"], 1)
            self.assertEqual([row["invite_id"] for row in data["items"]], [invite_id])
            self.assertEqual(data["counts"]["all"], 3)

    def test_expiration_boundary_agrees_with_existing_verification(self):
        row = self.db.get(UserInvite, 1)
        row.expires_at = NOW.replace(tzinfo=None)
        self.db.commit()
        for elapsed, expected in [(0, "pending"), (0.001, "expired")]:
            now = NOW + timedelta(seconds=elapsed)
            with patch.object(admin_invites, "_utcnow", return_value=now), patch("app.routes.invite_routes.utcnow_naive", return_value=now.replace(tzinfo=None)):
                _, data, _ = self.request("q=casey")
                self.assertEqual(data["items"][0]["status"], expected)
                self.assertEqual(data["items"][0]["remaining_seconds"], 0)
                self.assertEqual(verify_invite({"token": "test-token-1"}, self.db)["valid"], expected == "pending")

    def test_refresh_reflects_acceptance_and_elapsed_time(self):
        self.db.get(UserInvite, 1).used_at = NOW.replace(tzinfo=None)
        self.db.commit()
        _, data, _ = self.request("status=completed")
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["counts"]["pending"], 0)
        with patch.object(admin_invites, "_utcnow", return_value=NOW + timedelta(days=30)):
            _, data, _ = self.request("status=completed")
            self.assertEqual(data["total"], 2)

    def test_search_name_email_case_and_literal_wildcards(self):
        for search in ["q=CASEY", "q=Casey%20Smith", "q=casey%40example.invalid"]:
            _, data, _ = self.request(search)
            self.assertEqual([row["invite_id"] for row in data["items"]], [1])
        _, data, _ = self.request("q=lee&status=completed")
        self.assertEqual(data["counts"], {"all": 2, "pending": 0, "completed": 1, "expired": 1})
        for query in ["q=%25", "q=_", "q=%27%20OR%201%3D1"]:
            self.assertEqual(self.request(query)[1]["total"], 0)
        self.add_invite(4, "pending", first_name="100%", last_name="Ready")
        self.assertEqual(self.request("q=%25")[1]["total"], 1)

    def test_pagination_deterministic_order_and_repeated_email(self):
        self.add_invite(4, "pending", email="casey@example.invalid", created_at=self.db.get(UserInvite, 1).created_at)
        _, data, _ = self.request("page_size=1")
        self.assertEqual(data["items"][0]["invite_id"], 4)
        self.assertEqual(data["total"], 4)
        _, data, _ = self.request("page_size=1&page=2")
        self.assertEqual(data["items"][0]["invite_id"], 1)
        self.assertEqual(data["page"], 2)
        self.assertEqual(self.request("q=casey")[1]["total"], 2)
        self.assertEqual(self.request("page=999")[1]["items"], [])

    def test_empty_results_and_invalid_parameters(self):
        _, data, _ = self.request("q=missing")
        self.assertEqual(data["items"], [])
        self.assertEqual(data["counts"], {"all": 0, "pending": 0, "completed": 0, "expired": 0})
        for query in ["status=revoked", "page=0", "page=-1", "page_size=0", "page_size=101", "q=" + "a" * 201]:
            self.assertEqual(self.request(query)[0], 422)

    def test_missing_issuer_and_email_fallback_preserve_records(self):
        self.db.get(UserInvite, 1).created_by_user_id = None
        self.db.get(UserInvite, 2).created_by_user_id = self.member.user_id
        self.db.commit()
        _, data, _ = self.request()
        self.assertIsNone(data["items"][0]["created_by_name"])
        self.assertEqual(data["items"][1]["created_by_name"], "member@example.invalid")
        self.assertEqual(data["total"], 3)

    def test_response_excludes_secrets_and_does_not_change_invitations(self):
        before = [tuple(getattr(row, col.name) for col in UserInvite.__table__.columns) for row in self.db.query(UserInvite).order_by(UserInvite.invite_id).all()]
        _, data, _ = self.request()
        serialized = json.dumps(data)
        for field in ["token", "token_hash", "invite_url", "password_hash", "phone", "role_ids_json"]:
            self.assertNotIn(field, data["items"][0])
        self.assertNotIn("PRIVATE-PHONE", serialized)
        self.assertNotIn(token_hash("test-token-1"), serialized)
        self.db.expire_all()
        after = [tuple(getattr(row, col.name) for col in UserInvite.__table__.columns) for row in self.db.query(UserInvite).order_by(UserInvite.invite_id).all()]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
