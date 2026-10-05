import { test, afterEach } from "node:test";
import assert from "node:assert/strict";
import worker from "./worker.mjs";

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });
const env = {
  FORUM_REPLY_DOMAIN: "tsk9sar.org",
  FORUM_INBOUND_URL: "https://tsk9sar.org/api/forums/inbound-email",
  FORUM_INBOUND_SECRET: "test-secret-".repeat(4),
};
function message(overrides = {}) {
  return {
    from: "member@example.org", to: `forum+${"a".repeat(45)}@tsk9sar.org`,
    rawSize: 4, raw: new Blob(["test"]).stream(), rejected: null,
    setReject(reason) { this.rejected = reason; }, ...overrides,
  };
}
test("posts raw MIME with authenticated envelope, awaits backend acceptance", async () => {
  const msg = message();
  globalThis.fetch = async (url, options) => {
    assert.equal(url, env.FORUM_INBOUND_URL);
    assert.equal(options.redirect, "manual");
    assert.equal(options.headers["X-Forum-Envelope-To"], msg.to);
    assert.equal(options.headers["X-Forum-Envelope-From"], msg.from);
    assert.equal(options.headers.Authorization, `Bearer ${env.FORUM_INBOUND_SECRET}`);
    assert.equal(new TextDecoder().decode(options.body), "test");
    return Response.json({ ok: true });
  };
  await worker.email(msg, env);
  assert.equal(msg.rejected, null);
});
test("no-reply and unrelated addresses never reach the backend", async () => {
  globalThis.fetch = () => { assert.fail("unexpected network request"); };
  for (const to of ["no-reply@tsk9sar.org", "no-reply@sark9s.org", "forum@tsk9sar.org", `forum+${"a".repeat(45)}@other.org`]) {
    const msg = message({ to });
    await worker.email(msg, env);
    assert.ok(msg.rejected);
  }
});
test("oversized mail and missing configuration are rejected before fetch", async () => {
  globalThis.fetch = () => { assert.fail("unexpected network request"); };
  for (const [msg, config] of [[message({ rawSize: 1048577 }), env], [message(), {}],
    [message(), { ...env, FORUM_INBOUND_SECRET: "" }], [message(), { ...env, FORUM_INBOUND_URL: "http://example.org" }]]) {
    await worker.email(msg, config);
    assert.ok(msg.rejected);
  }
});
test("ambiguous failures retry and accept duplicate acknowledgment", async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    if (++calls === 1) throw new Error("connection reset");
    return Response.json({ ok: true, duplicate: true });
  };
  const msg = message();
  await worker.email(msg, env);
  assert.equal(calls, 2);
  assert.equal(msg.rejected, null);
});
test("permanent backend rejection is surfaced without retry", async () => {
  let calls = 0;
  globalThis.fetch = async () => { calls++; return Response.json({ detail: "Topic is locked" }, { status: 403 }); };
  const msg = message();
  await worker.email(msg, env);
  assert.equal(calls, 1);
  assert.equal(msg.rejected, "Topic is locked");
});
test("backend outage or HTML success response is never silently accepted", async () => {
  for (const response of [() => new Response("offline", { status: 503 }), () => new Response("<html>login</html>")]) {
    let calls = 0;
    globalThis.fetch = async () => { calls++; return response(); };
    const msg = message();
    await worker.email(msg, env);
    assert.equal(calls, 2);
    assert.match(msg.rejected, /not confirmed/);
  }
});
test("redirect responses are rejected and credentials never follow the redirect", async () => {
  let calls = 0;
  globalThis.fetch = async (url, options) => {
    calls++;
    assert.equal(url, env.FORUM_INBOUND_URL);
    assert.equal(options.redirect, "manual");
    return new Response(null, { status: 302, headers: { Location: "https://untrusted.example" } });
  };
  const msg = message();
  await worker.email(msg, env);
  assert.equal(calls, 2);
  assert.match(msg.rejected, /not confirmed/);
});
