// Attach ONLY the forum@tsk9sar.org routing rule with subaddressing enabled.
// No fetch handler, no forwarding, and no catch-all routing changes.
const MAX_RAW_BYTES = 1024 * 1024;

export default {
  async email(message, env) {
    const recipient = message.to.toLowerCase();
    const domain = (env.FORUM_REPLY_DOMAIN || "").toLowerCase();
    const [local, host, extra] = recipient.split("@");
    if (extra || host !== domain || !/^forum\+[a-z2-7]{45}$/.test(local)) {
      message.setReject("Invalid forum reply address. Please reply to a recent forum notification.");
      return;
    }
    if (message.rawSize > MAX_RAW_BYTES) {
      message.setReject("Forum replies must be under 1 MB. Remove attachments and try again.");
      return;
    }
    if (!env.FORUM_INBOUND_SECRET || env.FORUM_INBOUND_SECRET.length < 32
        || !env.FORUM_INBOUND_URL?.startsWith("https://")) {
      message.setReject("Forum email replies are unavailable. Please use the website.");
      return;
    }
    const raw = await new Response(message.raw).arrayBuffer();
    if (raw.byteLength > MAX_RAW_BYTES) {
      message.setReject("Forum replies must be under 1 MB. Remove attachments and try again.");
      return;
    }
    // Await acceptance before completing the SMTP event. Retry ambiguous failures
    // once; the database receipt makes a committed reply safe to deliver again.
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const response = await fetch(env.FORUM_INBOUND_URL, {
          method: "POST",
          // workerd supports only manual/follow. Never follow a redirect with
          // the shared secret; a 3xx response falls through to failure below.
          redirect: "manual",
          signal: AbortSignal.timeout(15000),
          headers: {
            "Authorization": `Bearer ${env.FORUM_INBOUND_SECRET}`,
            "Content-Type": "message/rfc822",
            "X-Forum-Envelope-From": message.from,
            "X-Forum-Envelope-To": recipient,
          },
          body: raw,
        });
        if (!response.ok) {
          console.warn("forum_inbound_http_failure", { status: response.status, attempt: attempt + 1 });
        }
        if (response.ok) {
          const result = await response.json();
          if (result.ok === true) return;
        } else if ([400, 403, 404, 413, 415, 422].includes(response.status)) {
          // Backend errors are intentionally fixed messages, never email content.
          const result = await response.json().catch(() => ({}));
          const reason = typeof result.detail === "string"
            ? result.detail.replace(/[\r\n]/g, " ").slice(0, 200)
            : "Reply could not be posted. Please use the forum website.";
          message.setReject(reason);
          return;
        }
      } catch (error) {
        // Log the error class only, never email content, addresses or secrets.
        console.warn("forum_inbound_request_failure", {
          name: error instanceof Error ? error.name : "Error", attempt: attempt + 1,
        });
      }
    }
    message.setReject("Forum reply was not confirmed. Please retry later or check the discussion on the website.");
  },
};
