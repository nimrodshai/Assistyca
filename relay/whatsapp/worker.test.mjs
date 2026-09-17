// Run: node --test relay/whatsapp/worker.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import worker, { Delivery, isFinal, retryDelayMs } from "./worker.js";

const SECRET = "app-secret";
const ORIGIN_URL = "https://portal.example";

function sign(body) {
  return "sha256=" + createHmac("sha256", SECRET).update(body).digest("hex");
}

function fakeStorage() {
  const data = new Map();
  return {
    data,
    alarm: null,
    async put(key, value) { data.set(key, structuredClone(value)); },
    async get(key) { return structuredClone(data.get(key)); },
    async deleteAll() { data.clear(); this.alarm = null; },
    async setAlarm(when) { this.alarm = when; },
  };
}

// One Durable Object per message, as Cloudflare would create them.
function fakeEnv() {
  const objects = [];
  const env = {
    ORIGIN_URL,
    WHATSAPP_APP_SECRET: SECRET,
    objects,
    DELIVERY: {
      newUniqueId: () => objects.length,
      get: () => {
        const storage = fakeStorage();
        const object = new Delivery({ storage }, env);
        objects.push({ object, storage });
        return { fetch: (url, init) => object.fetch(new Request(url, init)) };
      },
    },
  };
  return env;
}

function webhook(body, signature = sign(body)) {
  return new Request("https://hook.assistyca.com/webhooks/whatsapp", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Hub-Signature-256": signature },
    body,
  });
}

function withOrigin(responder, run) {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    return responder(calls.length);
  };
  return run(calls).finally(() => { globalThis.fetch = original; });
}

test("answers Meta at once and keeps the message", async () => {
  const env = fakeEnv();
  const body = '{"entry":[{"id":"1"}]}';
  await withOrigin(() => { throw new Error("must not reach the portal yet"); }, async () => {
    const reply = await worker.fetch(webhook(body), env);
    assert.equal(reply.status, 200);
  });
  assert.equal(env.objects.length, 1);
  const { storage } = env.objects[0];
  assert.equal(new TextDecoder().decode(storage.data.get("message").body), body);
  assert.notEqual(storage.alarm, null);
});

test("refuses a message Meta did not sign", async () => {
  const env = fakeEnv();
  const reply = await worker.fetch(webhook("{}", "sha256=" + "0".repeat(64)), env);
  assert.equal(reply.status, 403);
  assert.equal(env.objects.length, 0);
});

test("keeps trying through a deploy, then hands over the exact bytes and signature", async () => {
  const env = fakeEnv();
  const body = '{"text":"delete my account please"}';
  await worker.fetch(webhook(body), env);
  const { object, storage } = env.objects[0];

  const answers = [
    () => { throw new TypeError("connection refused"); },
    () => new Response("Bad gateway", { status: 502 }),
    () => new Response("ok", { status: 200 }),
  ];
  await withOrigin((n) => answers[n - 1](), async (calls) => {
    await object.alarm();
    assert.ok(storage.alarm > Date.now(), "retry scheduled after a refused connection");
    await object.alarm();
    assert.ok(storage.data.has("message"), "still held after a 502");
    await object.alarm();
    assert.equal(storage.data.size, 0, "dropped once the portal took it");
    assert.equal(storage.alarm, null);

    assert.equal(calls.length, 3);
    const last = calls[2];
    assert.equal(last.url, ORIGIN_URL + "/webhooks/whatsapp");
    assert.equal(last.init.headers["X-Hub-Signature-256"], sign(body));
    assert.equal(new TextDecoder().decode(last.init.body), body);
  });
});

test("stops when the portal refuses the message itself", () => {
  assert.equal(isFinal(200), true);
  assert.equal(isFinal(403), true);
  assert.equal(isFinal(400), true);
  assert.equal(isFinal(429), false);
  assert.equal(isFinal(502), false);
  assert.equal(isFinal(503), false);
});

test("tries every few seconds at first, then eases off", () => {
  assert.equal(retryDelayMs(10 * 1000), 3000);
  assert.equal(retryDelayMs(10 * 60 * 1000), 30000);
  assert.equal(retryDelayMs(2 * 60 * 60 * 1000), 300000);
});

test("passes Meta's handshake through to the portal", async () => {
  const env = fakeEnv();
  await withOrigin(() => new Response("challenge-123", { status: 200 }), async (calls) => {
    const reply = await worker.fetch(
      new Request("https://hook.assistyca.com/webhooks/whatsapp?hub.mode=subscribe&hub.challenge=challenge-123"),
      env,
    );
    assert.equal(await reply.text(), "challenge-123");
    assert.equal(calls[0].url, ORIGIN_URL + "/webhooks/whatsapp?hub.mode=subscribe&hub.challenge=challenge-123");
  });
});
