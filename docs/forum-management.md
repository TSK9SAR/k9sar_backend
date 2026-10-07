# Forum category management and topic moves

Implemented in `app/routes/admin_forum_management.py`, registered under
`/api/admin/forum`. The frontend exposes **Administrator → Manage Forums & Surveys**
at `/admin/forums`, with a link to the existing survey reports. A topic's
**Move Topic** link opens the page filtered to that discussion.

## Permissions and behavior

Every endpoint enforces `require_admin`. Writes and delete/move previews also
enforce `require_mfa_verified`. The role check is independent of frontend navigation.
Members and supervisors cannot manage categories or move topics.

Categories support a name, description, display order, visibility, minimum role
(`member`, `evaluator`, `supervisor`, `admin`) and default email preference (`none`,
`announcements`, `all`). Personal email preferences continue to apply. Slugs are
generated on creation and remain stable on rename; public URLs use category IDs.
Hidden categories are included in the administrative listing but unavailable via
normal forum routes and inbound email. Hiding preserves the entire discussion.

Only empty categories can be deleted. Delete confirmation rechecks the category
under a row lock and performs a direct DELETE; the topic foreign key also protects
against concurrent topic creation. No topic/content cascade is performed.

Moving changes `ForumTopic.category_id` and its automatic update timestamp. It
preserves topic/post IDs, timestamps used for unread activity, pin/lock state,
posts (including soft-deleted posts), polls, votes, feedback, attachments, stored
files, read markers and inbound email receipts. Destinations must be visible;
hidden source categories are supported. The user reviews the source/destination
access rules before confirming. A move may grant or revoke access to all existing
content in the discussion.

## Endpoints

All paths below have the prefix `/api/admin/forum`.

| Method | Path | Input / result |
| --- | --- | --- |
| GET | `/categories` | All categories, topic counts, configuration revision |
| POST | `/categories` | Category fields; returns created category (201) |
| PUT | `/categories/{id}` | Category fields and `expected_revision` |
| POST | `/categories/{id}/delete-preview` | Returns category, `confirm_text`, `confirmation_token`, `expires_at` |
| POST | `/categories/{id}/delete-confirm` | Exact `confirm_text` and `confirmation_token` |
| GET | `/topics` | Optional `q`, `category_id`, `topic_id`, `offset`, `limit` (default 25, maximum 100); returns `items`, `total` |
| POST | `/topics/{id}/move-preview` | `destination_category_id`; returns source/destination, content counts and confirmation token |
| POST | `/topics/{id}/move-confirm` | `destination_category_id`, `confirmation_token` |

Category edits use a SHA-256 revision of the current category configuration and a
row lock to reject stale overwrites. Delete/move tokens expire in five minutes,
use purpose-separated HMAC-SHA256 with the application's configured JWT signing
secret, and bind the action, actor and reviewed state. They are not login tokens.
No new secret is needed; supported secret variable precedence matches the JWT
helper (`JWT_SECRET_KEY`, `JWT_SECRET`, `SECRET_KEY`). A missing secret fails closed.
Never log confirmation tokens or credentials.

Changed source/destination settings or topic category invalidate a move preview.
Counts are also included, so added content may require reviewing again. Repeated
confirmations fail because the topic has already moved or the category is gone.
Invalid/stale/expired previews and nonempty deletes return 409; missing entities
return 404. Reload/review rather than retrying the same confirmation indefinitely.

## Email behavior

Neither settings changes nor moves send email. Background topic/reply notification
jobs resolve the topic's current category at execution time, rather than using the
category ID captured when queued. Hidden categories send no notifications. Future
notifications use the destination's access and email preferences. Already-sent
emails cannot be withdrawn, and a notification job already sending mail is not a
durable, transactionally synchronized queue.

Inbound email tokens remain bound to user/topic/email, and the existing handler
checks the current category's visibility and role requirements on every reply.
Members who lose access cannot reply through an old email. No Worker routing or
no-reply/catch-all forwarding changes are needed.

## Verification and release

Use an isolated checkout and dependencies; never import `app.main` for tests.
The tests inject SQLite before importing production database-dependent modules
and mock email delivery. Run both suites:

```bash
python -m unittest discover -s tests -p 'test_forum_management.py' -v
python -m unittest discover -s tests -p 'test_forum_email*.py' -v
```

On 2026-10-07, 11 management tests and 16 email tests passed in network-disabled
containers with source mounted over `/app` and no production environment file.
Management coverage includes role/MFA rejection on every route, category validation
and stale edits, deletion safeguards, confirmation expiry/tampering/actor binding,
hidden categories, pagination/search, complete discussion preservation, current
inbound email permissions and queued notification category selection.

Deploy the backend before the frontend. No schema migration, new environment
variable, file migration or Worker deployment is required. Use the canonical
[maintenance guide](https://github.com/TSK9SAR/k9sar_frontend/blob/main/docs/MAINTENANCE_AND_HANDOFF.md)
for the production container's three mounts, build exclusions and rollback.
Rolling back the code leaves category settings and completed topic moves in the
existing database; restore them through a reviewed management operation if needed.
