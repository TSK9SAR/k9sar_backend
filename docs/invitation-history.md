# Invitation history

Administrators can review retained invitations at `/admin/invitations`, accessible
through **Administrator → Invitation History**. The existing creation form remains
at `/admin/invites` and is linked from the history page.

The read-only endpoint is `GET /api/admin/invites` in `app/routes/admin_invites.py`.
It enforces `require_admin`; members and supervisors cannot read the global history.
It does not change the existing supervisor/admin `POST /api/admin/invites` flow,
invitation verification/acceptance, or email delivery behavior.

Query parameters:

| Parameter | Values / default |
| --- | --- |
| `status` | `all` (default), `pending`, `completed`, `expired` |
| `q` | Recipient name or email; case-insensitive literal substring, maximum 200 characters |
| `page` | One-based, default 1 |
| `page_size` | 1–100, default 25 |

The response contains `items`, `total` for the active status/search, `counts` across
statuses for the current search, `page`, `page_size`, and UTC `evaluated_at`.
Items include ID, recipient name/email, issuer display name, UTC creation/expiry/
completion timestamps, status and remaining seconds. Status uses one server time
for filtering, counts and rows:

- **Completed**: `used_at` is not null, even after the original expiration.
- **Expired**: unused and `expires_at < evaluated_at`.
- **Pending**: unused and `expires_at >= evaluated_at`.

The comparison matches existing invitation verification and acceptance. Remaining
seconds are zero for completed/expired invitations. MySQL naive timestamps are
interpreted as UTC and returned with an explicit timezone. The frontend renders
local times, refreshes while visible every minute, and refreshes on tab return.
Newest issuance sorts first, with descending ID as a stable tie-breaker.

Responses use an explicit Pydantic schema and `Cache-Control: no-store`. Tokens,
token hashes, invitation links, phone numbers and password data are not selected
or returned. Missing issuer records preserve the invitation through an outer join;
repeated invitations to an email remain separate records. No database migration,
new environment variable, or email route change is required.

These records prove invitation issuance/acceptance, not SMTP delivery or message
opens. The existing mail send result is not persisted in `user_invites`. This page
does not reconstruct deleted records or provide an immutable audit trail.

Run the isolated tests (they replace `app.database` before app imports):

```bash
python -m unittest discover -s tests -p 'test_invitation_history.py' -v
```

Ten tests cover administrator-only access, all statuses, exact expiry boundary
agreement with invitation verification, completed precedence, automatic status
changes, UTC serialization, counts, safe search, pagination, missing issuer data,
secret exclusion and read-only invitation access. All test data is synthetic;
no real invitations are sent. Use the project maintenance guide for deployment
with the existing three storage mounts and rollback procedure.
