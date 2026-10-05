# K9SAR backend

FastAPI/SQLAlchemy backend for Tri-State K9 Search & Rescue membership,
certifications, standards, public verification, forums and administration.

- [Project maintenance and handoff](docs/MAINTENANCE_AND_HANDOFF.md)
- [Forum email replies](docs/forum-email-replies.md)
- [Frontend repository](https://github.com/TSK9SAR/k9sar_frontend)

Production source is `/home/ubuntu/k9sar_backend`; the running container is
`k9sar_api` with `backend.env`, host MySQL, and three persistent bind mounts.
Read the project guide before deployment: the checked-in redeploy/backup/restore
scripts differ from the installed production configuration.

## Development and tests

Use Python 3.11, `requirements.txt`, and an isolated MySQL 8 database. Configure
independent development secrets and a mail sink. Importing `app.database` or
`app.main` connects to the configured database and invokes `create_all`; do not
point development or import-based probes at production.

The forum regression suite deliberately injects SQLite before database imports
and mocks notification delivery:

```bash
python -m unittest discover -s tests -p 'test_forum_email*.py' -v
node --test cloudflare/forum-email/worker.test.mjs
```

Also run `worker.runtime.test.mjs` with Miniflare as described in the email guide.
The wider application does not yet have a verified complete test/seed/migration
workflow. See the project guide for current gaps and release acceptance checks.
