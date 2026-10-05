# Forum replies through Cloudflare Email Routing

Forum notifications can use `forum+<45-character-token>@tsk9sar.org` as Reply-To.
The sender/SMTP_FROM and existing no-reply forwarding remain unchanged. Website
links remain in all notifications. Replies create comments on existing topics;
email cannot create topics, vote, upload attachments, or sign into the app.

## Configuration and activation

Backend environment (the running service uses `backend.env`):

```dotenv
FORUM_EMAIL_REPLIES_ENABLED=false
FORUM_REPLY_DOMAIN=tsk9sar.org
FORUM_REPLY_SECRET=<independent random secret of at least 32 characters>
FORUM_INBOUND_SECRET=<independent random secret of at least 32 characters>
```

Generate each secret with `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`.
Keep secrets outside source control. Put the same FORUM_INBOUND_SECRET in the
Worker using `wrangler secret put FORUM_INBOUND_SECRET` from `cloudflare/forum-email`.
The reply signing secret stays exclusively on the backend.

1. Deploy the backend code. Its existing startup `Base.metadata.create_all`
   creates the additive `forum_email_receipts` table. No existing tables change.
2. Verify `https://tsk9sar.org/api/forums/inbound-email` reaches the API (not the
   frontend SPA); while disabled it returns 503 for a POST. Allow a 1 MB MIME body
   through the reverse proxy. Nginx's default 1m limit matches this feature.
3. From `cloudflare/forum-email`, run `npx wrangler login`, then
   `npx wrangler deploy`, then `npx wrangler secret put FORUM_INBOUND_SECRET`.
   At the secret prompt, paste only the matching value from `backend.env`.
   For the first deployment, upload the Worker before adding its secret. The
   configuration intentionally has no `addresses` field and changes no routing rules.
4. In Cloudflare Email Routing for **tsk9sar.org**, enable subaddressing, then add
   ONLY **forum@tsk9sar.org → Send to a Worker → k9sar-forum-email**. Confirm this
   address has no pre-existing rule before adding it. Preserve all no-reply,
   other address and catch-all rules. Do not point no-reply or catch-all at this Worker.
5. Set `FORUM_EMAIL_REPLIES_ENABLED=true` and restart/redeploy the backend with
   its existing environment/mounts. New notifications now have reply addresses.
6. With an authorized test member/topic, receive a new notification and reply
   with text above its quote. Check one comment and normal reply notifications.
   Repeat the same delivery to verify only one post; also test a locked topic,
   another sender, and a normal email to no-reply to confirm forwarding.

Disable with `FORUM_EMAIL_REPLIES_ENABLED=false` and restart. Notification emails
return to their previous Reply-To/body behavior. Leave no-reply forwarding alone.
Rotating FORUM_REPLY_SECRET revokes all outstanding reply addresses.

## Behavior and limits

- A reply token expires in 30 days and is bound to a user, topic, and the user's
  current email. It is a bearer capability: recipients should not share it.
  Possession plus matching envelope/header From authenticates a reply; this does
  not claim to independently verify DKIM/DMARC. Cloudflare supplies SMTP filtering.
- Only the Worker shared secret can call the ingress. HTTPS is required and the
  Worker will not follow redirects that could leak the shared secret.
- Active membership, active category, current category permissions, and topic
  locking are checked on each reply (admins retain the website's lock override).
- Extract only the MIME plain-text body. Ignore HTML and attachments, including
  nested attached messages. Reject HTML-only/attachment-only and automated mail.
  1 MB raw MIME maximum; 20 KB UTF-8 reply text maximum.
- Strip common quoted-history boundaries, the notification marker, standard
  signatures and common mobile signatures. This is intentionally top-post only;
  inline/bottom replies and unusual mail-client quote formats are not supported.
- Plain text is stored in the existing body_md field; forum Markdown rendering
  remains unchanged. There is no HTML import or attachment storage.
- A SHA-256 receipt scoped to member/topic/Message-ID is committed atomically
  with the post. Messages without Message-ID use their raw MIME hash. Keep
  receipts when deleting posts, so replay cannot recreate a moderated post.
- The Worker awaits acceptance and retries once on ambiguous failures. Permanent
  errors and outages reject the SMTP message with a short reason rather than
  silently dropping it; this does not promise automatic Cloudflare redelivery.
- Notifications use the existing background task path after commit. As with web
  posts, a process crash after commit can lose notification delivery; duplicates
  do not resend notifications. No emails are sent by the automated test suite.

## Verification

Run `python -m unittest discover -s tests -p 'test_forum_email*.py' -v` in an
isolated copy/container with the backend's dependencies installed. The integration
test injects an in-memory SQLite database before importing application models;
it never connects to the production database. Run Worker tests with
`node --test cloudflare/forum-email/worker.test.mjs` (Node 20+).

Also run the workerd regression test after changing Worker network options:
from `cloudflare/forum-email`, install Miniflare with `npm install --no-save miniflare`
and run `node --test worker.test.mjs worker.runtime.test.mjs`. Alternatively set
`MINIFLARE_MODULE` to an existing Miniflare package directory. This exercises the
actual Cloudflare Request API and verifies redirects cannot leak credentials.
The Worker uses `redirect: "manual"`; `redirect: "error"` throws in workerd before
making a request, even though Node's fetch accepts it.

Cloudflare references: [email handler](https://developers.cloudflare.com/email-service/api/route-emails/email-handler/)
and [routing/subaddressing](https://developers.cloudflare.com/email-service/configuration/email-routing-addresses/).
