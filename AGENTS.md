# Working on the K9SAR backend

Read `docs/MAINTENANCE_AND_HANDOFF.md` and the linked project guide before changing
infrastructure, deployment, database, authentication or email behavior. Update
operating documentation with changes.

- API entry: `app/main.py`; routes: `app/routes/`; models: `app/models/`.
- Importing `app.database` or `app.main` connects to the configured DB and calls
  `create_all`. Use isolated databases for development, tests and import probes.
- Run the isolated forum tests with
  `python -m unittest discover -s tests -p 'test_forum_email*.py' -v`.
  Category/move changes also require
  `python -m unittest discover -s tests -p 'test_forum_management.py' -v`.
- Worker changes need both Node tests and the workerd runtime test; see
  `docs/forum-email-replies.md`. Keep redirect refusal and receipt idempotency.
- Keep credentials, environment files, private keys and member data out of commits
  and output. Do not copy the installed backup script's inline credential to Git.
- Production uses `backend.env` and three persistent mounts. Existing redeploy,
  backup and restore scripts have documented differences from production.
- Enforce roles, access and MFA at the backend; preserve preview/confirm flows for
  destructive administration.
- Forum email replies are text-only and use the dedicated Cloudflare forum route.
  Preserve existing no-reply, other address and catch-all forwarding.
