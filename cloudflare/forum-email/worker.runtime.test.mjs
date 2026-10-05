import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";

// npm install --no-save miniflare, or set MINIFLARE_MODULE to an installed
// Miniflare package directory. Exercises the real workerd Request API.
const require = createRequire(import.meta.url);
const { Miniflare, convertV4MiniflareOptions } = require(process.env.MINIFLARE_MODULE || "miniflare");

test("workerd posts MIME to backend and refuses redirects without forwarding credentials", async () => {
  const source = await readFile(new URL("./worker.mjs", import.meta.url), "utf8");
  const script = source.replace("export default", "const handler =") + `
    export default {async fetch(request) {
      const msg = {
        to: 'forum+' + 'a'.repeat(45) + '@tsk9sar.org',
        from: 'member@example.org', rawSize: 4,
        raw: new Response('test').body, rejected: null,
        setReject(reason) { this.rejected = reason; },
      };
      await handler.email(msg, {
        FORUM_REPLY_DOMAIN: 'tsk9sar.org',
        FORUM_INBOUND_URL: 'https://backend.example' + new URL(request.url).pathname,
        FORUM_INBOUND_SECRET: 'test-secret-'.repeat(4),
      });
      return Response.json({rejected:msg.rejected});
    }};
  `;
  const calls = [];
  const options = {
    modules: true, compatibilityDate: "2026-10-04", script,
    outboundService: async (request) => {
      calls.push(request.url);
      assert.equal(new URL(request.url).host, "backend.example");
      assert.equal(request.headers.get("Authorization"), `Bearer ${"test-secret-".repeat(4)}`);
      assert.equal(await request.text(), "test");
      return request.url.endsWith("/redirect")
        ? new Response(null, {status:302, headers:{Location:"https://untrusted.example"}})
        : Response.json({ok:true});
    },
  };
  const runtime = new Miniflare(convertV4MiniflareOptions ? convertV4MiniflareOptions(options) : options);
  try {
    const accepted = await (await runtime.dispatchFetch("http://localhost/accept")).json();
    assert.equal(accepted.rejected, null);
    assert.equal(calls.length, 1);
    const redirected = await (await runtime.dispatchFetch("http://localhost/redirect")).json();
    assert.match(redirected.rejected, /not confirmed/);
    assert.deepEqual(calls, ["https://backend.example/accept", "https://backend.example/redirect", "https://backend.example/redirect"]);
  } finally {
    await runtime.dispose();
  }
});
