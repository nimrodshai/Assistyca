// WhatsApp webhook relay.
//
// Production keeps its data on a disk only one server can hold, so every
// deploy stops the old server before the new one starts. A message WhatsApp
// delivers in that gap is refused, and Meta's own retry comes minutes later.
//
// This Worker stands in front of the portal: it tells Meta "received" at once,
// keeps the message, and hands it to the portal, trying again every few
// seconds until the portal takes it. Each message is its own Durable Object,
// so a slow reply to one never holds up another.
//
// The portal still checks the signature and still refuses a message it has
// already answered, so a message handed over twice is answered once.

const WEBHOOK_PATH = "/webhooks/whatsapp";
const MAX_BODY_BYTES = 1024 * 1024;
// A reply runs a model; give the portal as long as it needs, short of the
// fifteen minutes an alarm is allowed to run.
const DELIVERY_TIMEOUT_MS = 10 * 60 * 1000;
// Past this the message is stale; Meta itself stops retrying within days.
const GIVE_UP_AFTER_MS = 24 * 60 * 60 * 1000;

export function retryDelayMs(ageMs) {
  if (ageMs < 5 * 60 * 1000) return 3 * 1000;
  if (ageMs < 60 * 60 * 1000) return 30 * 1000;
  return 5 * 60 * 1000;
}

// The portal has the message, or will never take it: stop trying.
export function isFinal(status) {
  if (status >= 200 && status < 300) return true;
  return status >= 400 && status < 500 && status !== 408 && status !== 429;
}

async function signatureIsValid(secret, body, header) {
  if (!header || !header.startsWith("sha256=")) return false;
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const digest = new Uint8Array(await crypto.subtle.sign("HMAC", key, body));
  const expected = [...digest].map((b) => b.toString(16).padStart(2, "0")).join("");
  const given = header.slice("sha256=".length).toLowerCase();
  if (given.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i += 1) diff |= given.charCodeAt(i) ^ expected.charCodeAt(i);
  return diff === 0;
}

function log(event, fields = {}) {
  console.log(JSON.stringify({ event, ...fields }));
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname.replace(/\/+$/, "") !== WEBHOOK_PATH) {
      return new Response("Not found", { status: 404 });
    }

    // Meta's one-time handshake when the address is set: the portal answers it.
    if (request.method === "GET") {
      const origin = new URL(WEBHOOK_PATH + url.search, env.ORIGIN_URL);
      const reply = await fetch(origin, { method: "GET" });
      return new Response(reply.body, { status: reply.status, headers: reply.headers });
    }

    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }

    const body = await request.arrayBuffer();
    if (body.byteLength > MAX_BODY_BYTES) {
      return new Response("Too large", { status: 413 });
    }
    const signature = request.headers.get("X-Hub-Signature-256") || "";
    if (env.WHATSAPP_APP_SECRET && !(await signatureIsValid(env.WHATSAPP_APP_SECRET, body, signature))) {
      log("relay_rejected", { reason: "invalid_signature" });
      return new Response("Invalid signature", { status: 403 });
    }

    const stub = env.DELIVERY.get(env.DELIVERY.newUniqueId());
    await stub.fetch("https://relay/enqueue", {
      method: "POST",
      headers: {
        "X-Hub-Signature-256": signature,
        "Content-Type": request.headers.get("Content-Type") || "application/json",
      },
      body,
    });
    return new Response("EVENT_RECEIVED", { status: 200 });
  },
};

export class Delivery {
  constructor(state, env) {
    this.storage = state.storage;
    this.env = env;
  }

  async fetch(request) {
    await this.storage.put("message", {
      body: new Uint8Array(await request.arrayBuffer()),
      signature: request.headers.get("X-Hub-Signature-256") || "",
      contentType: request.headers.get("Content-Type") || "application/json",
      receivedAt: Date.now(),
      attempts: 0,
    });
    await this.storage.setAlarm(Date.now());
    return new Response("queued");
  }

  async alarm() {
    const message = await this.storage.get("message");
    if (!message) return;

    message.attempts += 1;
    let status = 0;
    let error = "";
    try {
      const reply = await fetch(new URL(WEBHOOK_PATH, this.env.ORIGIN_URL), {
        method: "POST",
        headers: {
          "Content-Type": message.contentType,
          "X-Hub-Signature-256": message.signature,
          "X-Relay-Attempt": String(message.attempts),
        },
        body: message.body,
        signal: AbortSignal.timeout(DELIVERY_TIMEOUT_MS),
      });
      status = reply.status;
      await reply.body?.cancel();
    } catch (exc) {
      error = String(exc && exc.message ? exc.message : exc).slice(0, 200);
    }

    const ageMs = Date.now() - message.receivedAt;
    if (status && isFinal(status)) {
      if (message.attempts > 1 || status >= 300) {
        log("relay_delivered", { status, attempts: message.attempts, waitedMs: ageMs });
      }
      await this.storage.deleteAll();
      return;
    }
    if (ageMs > GIVE_UP_AFTER_MS) {
      log("relay_gave_up", { status, error, attempts: message.attempts, waitedMs: ageMs });
      await this.storage.deleteAll();
      return;
    }
    log("relay_retrying", { status, error, attempts: message.attempts, waitedMs: ageMs });
    await this.storage.put("message", message);
    await this.storage.setAlarm(Date.now() + retryDelayMs(ageMs));
  }
}
