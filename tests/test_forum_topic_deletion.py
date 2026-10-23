"""Destructive topic management regressions using isolated SQLite and mocked files."""
from datetime import datetime
import unittest
from unittest.mock import patch

from sqlalchemy import text
from fastapi import HTTPException
import test_forum_management as existing
from app.models.forum import (ForumTopic, ForumPost, ForumBallot, ForumBallotChoice,
                              ForumBallotVote, ForumBallotFeedback, ForumTopicRead,
                              ForumEmailReceipt)
from app.models.stored_files import StoredFile, ForumPostAttachment, EmailCampaignAttachment
from app.models.email_campaigns import EmailCampaign
from app.models.role import Role

database = existing.database
management = existing.management


class TopicDeletionTests(unittest.TestCase):
    request = existing.ForumManagementTests.request

    def setUp(self):
        existing.ForumManagementTests.setUp(self)
        extra = [EmailCampaign.__table__, EmailCampaignAttachment.__table__]
        database.Base.metadata.create_all(database.engine, tables=extra)
        self.tables.extend(extra)
        self.files = patch.object(management, "delete_physical_file", return_value=True)
        self.delete_file = self.files.start()

    def tearDown(self):
        self.files.stop()
        self.db.rollback()
        with database.engine.connect() as conn:
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            conn.execute(text("DROP TABLE IF EXISTS deletion_guard"))
        existing.ForumManagementTests.tearDown(self)

    def preview(self, topic_id=1):
        status, result = self.request("POST", f"/topics/{topic_id}/delete-preview")
        self.assertEqual(status, 200, result)
        return result

    def confirm(self, preview, topic_id=1, **overrides):
        body = {"confirmation_token": preview["confirmation_token"], "confirm_text": preview["confirm_text"], **overrides}
        return self.request("POST", f"/topics/{topic_id}/delete-confirm", body)

    def content(self):
        self.db.add(ForumTopic(topic_id=2, category_id=2, title="Keep me", created_by_user_id=2))
        self.db.add_all([
            ForumPost(post_id=10, topic_id=1, body_md="Opening", created_by_user_id=2),
            ForumPost(post_id=11, topic_id=1, body_md="Removed", created_by_user_id=2, deleted_at=datetime(2026, 1, 1)),
            ForumPost(post_id=20, topic_id=2, body_md="Unrelated", created_by_user_id=2),
            ForumBallot(ballot_id=10, topic_id=1, post_id=10, title="Poll", created_by_user_id=2),
            ForumBallot(ballot_id=11, topic_id=1, post_id=None, title="Topic poll", created_by_user_id=2),
            ForumBallotChoice(choice_id=10, ballot_id=10, label="Yes"),
            ForumBallotVote(vote_id=10, ballot_id=10, choice_id=10, user_id=2),
            ForumBallotFeedback(feedback_id=10, ballot_id=10, choice_id=10, user_id=2, feedback_text="Feedback"),
            ForumTopicRead(user_id=2, topic_id=1),
            ForumTopicRead(user_id=2, topic_id=2),
            ForumEmailReceipt(delivery_key="a" * 64, post_id=10),
            EmailCampaign(campaign_id=1, sent_by_user_id=2, subject="Example", body_text="Example", filter_json={}),
        ])
        for file_id in range(1, 4):
            self.db.add(StoredFile(file_id=file_id, original_filename=f"test{file_id}.txt", stored_filename=f"test{file_id}.txt",
                                   file_size=3, sha256_hash="a" * 64, storage_path=f"test{file_id}.txt", uploaded_by_user_id=2))
            self.db.add(ForumPostAttachment(attachment_id=file_id, post_id=10, file_id=file_id))
        self.db.add(ForumPostAttachment(attachment_id=4, post_id=20, file_id=2))
        self.db.add(EmailCampaignAttachment(attachment_id=1, campaign_id=1, file_id=3))
        self.db.commit()
        # Fixture inserts precede FK activation because the inherited minimal user
        # setup intentionally omits unrelated parent tables. Deletes enforce FKs.
        with database.engine.connect() as conn:
            conn.execute(text("PRAGMA foreign_keys=ON"))
            self.assertEqual(conn.execute(text("PRAGMA foreign_keys")).scalar(), 1)

    def test_complete_tree_deleted_with_foreign_keys_and_shared_files_preserved(self):
        self.content()
        preview = self.preview()
        self.assertEqual([preview[k] for k in ("post_count", "poll_count", "vote_count", "feedback_count", "attachment_count")], [2, 2, 1, 1, 3])
        self.assertNotIn("Opening", str(preview))
        with patch.object(existing.notifications, "send_email") as send:
            status, result = self.confirm(preview)
            self.assertEqual(status, 200, result)
            send.assert_not_called()
        self.assertIsNone(self.db.get(ForumTopic, 1))
        self.assertEqual([p.post_id for p in self.db.query(ForumPost)], [20])
        for model in (ForumBallot, ForumBallotChoice, ForumBallotVote, ForumBallotFeedback):
            self.assertEqual(self.db.query(model).count(), 0)
        self.assertEqual([r.topic_id for r in self.db.query(ForumTopicRead)], [2])
        self.assertEqual([r.file_id for r in self.db.query(StoredFile).order_by(StoredFile.file_id)], [2, 3])
        self.assertEqual(self.db.query(ForumPostAttachment).one().post_id, 20)
        self.assertEqual(self.db.query(EmailCampaignAttachment).count(), 1)
        self.assertEqual(self.db.query(ForumEmailReceipt).count(), 1)
        self.delete_file.assert_called_once_with("test1.txt")
        self.assertEqual(result["file_cleanup_pending"], 0)

    def test_empty_locked_hidden_topic_and_long_title_can_be_deleted(self):
        self.topic.title = "Long topic " * 18
        self.topic.is_locked = self.topic.is_pinned = True
        self.topic.category_id = 3
        self.db.commit()
        preview = self.preview()
        self.assertFalse(preview["category"]["is_active"])
        self.assertEqual(preview["confirm_text"], "DELETE TOPIC 1")
        self.assertEqual(self.confirm(preview)[0], 200)
        self.assertEqual(self.confirm(preview)[0], 404)
        self.assertEqual(self.request("POST", "/topics/999/delete-preview")[0], 404)
        self.delete_file.assert_not_called()

    def test_wrong_text_tampered_expired_other_actor_and_other_action_rejected(self):
        preview = self.preview()
        self.assertEqual(self.confirm(preview, confirm_text="DELETE")[0], 400)
        self.assertEqual(self.confirm(preview, confirmation_token="invalid")[0], 409)
        with patch.object(management.time, "time", return_value=preview["expires_at"]):
            self.assertEqual(self.confirm(preview)[0], 409)
        self.author.roles.append(self.db.get(Role, 3)); self.db.commit()
        self.current_user = self.author
        self.assertEqual(self.confirm(preview)[0], 409)
        self.current_user = self.user
        _, move = self.request("POST", "/topics/1/move-preview", {"destination_category_id": 2})
        self.assertEqual(self.confirm(preview, confirmation_token=move["confirmation_token"])[0], 409)
        self.assertIsNotNone(self.db.get(ForumTopic, 1))

    def test_changed_contents_permissions_and_same_count_edits_require_new_review(self):
        self.content()
        changes = [(ForumPost, 10, "body_md", "Edited body"), (ForumBallot, 10, "title", "Edited poll"),
                   (ForumBallotChoice, 10, "label", "Changed choice"),
                   (ForumBallotFeedback, 10, "feedback_text", "Edited feedback"),
                   (ForumPostAttachment, 1, "sort_order", 5), (ForumTopic, 1, "title", "Renamed")]
        for model, pk, field, value in changes:
            with self.subTest(model=model.__name__):
                preview = self.preview()
                setattr(self.db.get(model, pk), field, value); self.db.commit()
                self.assertEqual(self.confirm(preview)[0], 409)
        preview = self.preview()
        self.category.min_role = "admin"; self.db.commit()
        self.assertEqual(self.confirm(preview)[0], 409)
        preview = self.preview()
        self.db.add(ForumPost(post_id=12, topic_id=1, body_md="New reply", created_by_user_id=2)); self.db.commit()
        self.assertEqual(self.confirm(preview)[0], 409)
        self.delete_file.assert_not_called()

    def test_topic_move_and_new_vote_invalidate_preview(self):
        self.content()
        preview = self.preview()
        self.topic.category_id = 2; self.db.commit()
        self.assertEqual(self.confirm(preview)[0], 409)
        preview = self.preview()
        self.db.add(ForumBallotVote(vote_id=11, ballot_id=10, choice_id=10, user_id=1)); self.db.commit()
        self.assertEqual(self.confirm(preview)[0], 409)

    def test_read_marker_updates_do_not_invalidate_review(self):
        self.content()
        preview = self.preview()
        self.db.query(ForumTopicRead).filter_by(topic_id=1).update({"last_read_at": datetime(2026, 10, 23)})
        self.db.commit()
        self.assertEqual(self.confirm(preview)[0], 200)

    def test_foreign_key_failure_rolls_back_all_deletes_and_never_removes_files(self):
        self.content()
        with database.engine.begin() as conn:
            conn.execute(text("CREATE TABLE deletion_guard (topic_id INTEGER REFERENCES forum_topics(topic_id))"))
            conn.execute(text("INSERT INTO deletion_guard VALUES (1)"))
        self.assertEqual(self.confirm(self.preview())[0], 409)
        self.assertIsNotNone(self.db.get(ForumTopic, 1))
        self.assertEqual(self.db.query(ForumPost).count(), 3)
        self.assertEqual(self.db.query(ForumBallot).count(), 2)
        self.assertEqual(self.db.query(ForumPostAttachment).count(), 4)
        self.assertEqual(self.db.query(StoredFile).count(), 3)
        self.delete_file.assert_not_called()

    def test_physical_cleanup_failure_reports_success_with_warning(self):
        self.content()
        self.delete_file.side_effect = OSError("isolated file failure")
        with self.assertLogs(management.logger, level="WARNING"):
            status, result = self.confirm(self.preview())
        self.assertEqual(status, 200)
        self.assertEqual(result["file_cleanup_pending"], 1)
        self.assertIsNone(self.db.get(ForumTopic, 1))

    def test_old_email_replies_and_queued_notifications_cannot_recreate_deleted_topic(self):
        first = existing.email_tests.ReplyIntegrationTests.accept(self)
        self.assertEqual(self.confirm(self.preview())[0], 200)
        self.assertEqual(self.db.query(ForumEmailReceipt).one().post_id, first["post_id"])
        with self.assertRaises(HTTPException) as caught:
            existing.email_tests.ReplyIntegrationTests.accept(self)
        self.assertEqual(caught.exception.status_code, 404)
        with patch.object(existing.notifications, "send_email") as send:
            existing.notifications.send_new_reply_notifications(category_id=1, topic_id=1, post_id=first["post_id"],
                                                               author_user_id=1, public_base_url="https://example.org")
            send.assert_not_called()
        self.assertEqual(self.db.query(ForumPost).count(), 0)


if __name__ == "__main__":
    unittest.main()
