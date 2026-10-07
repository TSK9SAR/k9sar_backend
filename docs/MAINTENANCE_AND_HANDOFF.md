# K9SAR project maintenance and handoff

The canonical project-wide guide is maintained in the frontend repository:

**[Read the maintenance and handoff guide](https://github.com/TSK9SAR/k9sar_frontend/blob/main/docs/MAINTENANCE_AND_HANDOFF.md)**

For a new checkout, clone both repositories and read the frontend file
`docs/MAINTENANCE_AND_HANDOFF.md`. The owner's standalone copy is
`C:\dev\K9SAR_Maintenance_and_Handoff.md`. Repository links reflect the guide after
its documentation changes are committed and pushed.

The guide covers architecture, code ownership, access, runtime configuration,
local development, tests, deployment/rollback, database and file recovery,
maintenance, incident response, known gaps and successor acceptance. It was
verified against source and selected live read-only checks on 2026-10-05.

Keep project-wide procedures in that one canonical guide. Keep backend email
implementation details in [forum-email-replies.md](forum-email-replies.md).
Category maintenance and topic moves are described in
[forum-management.md](forum-management.md).
Update the guide with infrastructure changes; do not store credentials or member
records in documentation.

## Immediate backend orientation

- Entry point: `app/main.py`; database: `app/database.py` and `app/models/`.
- Live container: `k9sar_api`; configuration: `backend.env`.
- DB: host MySQL, schema `k9sar`; the Compose layout is not the live topology.
- Preserve `/var/k9sar/uploads`, `/var/www/k9sar_signatures`, and
  `/var/sark9/private_videos` bind mounts.
- Local health: `curl -fsS http://127.0.0.1:8000/health`; public `/health` is SPA
  fallback, not an API health check.
- Changing `backend.env` requires container recreation; Docker restart alone does
  not reload the environment file.
- Importing database/main modules can create tables. Use isolated development and
  review schema changes explicitly.
- Installed backup/restore helpers differ from the repository scripts; follow the
  guide's verified inventory and perform a full isolated restore rehearsal.
- Preserve no-reply/catch-all forwarding; forum inbound mail has its own route.
