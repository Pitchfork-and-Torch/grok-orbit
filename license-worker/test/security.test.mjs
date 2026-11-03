// Run: node --test test/   (Node 20+; uses the global Web Crypto)
import { test } from "node:test";
import assert from "node:assert/strict";
import worker from "../src/index.js";

function makeEnv() {
  const store = new Map();
  const mails = [];
  const KV = {
    async get(k, type) { const v = store.get(k); if (v == null) return null; return type === "json" ? JSON.parse(v) : v; },
    async put(k, v) { store.set(k, v); },
  };
  globalThis.fetch = async (url, init) => {
    if (String(url).includes("mail.test")) { mails.push(JSON.parse(init.body)); return new Response("{}"); }
    throw new Error("unexpected fetch " + url);
  };
  return { env: { KV, EMAIL_SEND_URL: "https://mail.test/send", EMAIL_TOKEN: "t" }, store, mails };
}
const post = (path, body, ip = "1.1.1.1") =>
  new Request("https://orbit.test" + path, { method: "POST", headers: { "Content-Type": "application/json", "CF-Connecting-IP": ip }, body: JSON.stringify(body) });

async function register(env, email, ip) { return worker.fetch(post("/v1/register", { email }, ip), env); }
function lastCode(mails) { const m = JSON.stringify(mails.at(-1)).match(/code is (\d{6})/); return m && m[1]; }

test("code is 6 digits, stored hashed, never in plain text", async () => {
  const { env, store, mails } = makeEnv();
  const r = await register(env, "a@x.com");
  assert.equal(r.status, 200);
  const code = lastCode(mails);
  assert.match(code, /^\d{6}$/);
  const rec = JSON.parse(store.get("mail:a@x.com"));
  assert.equal(rec.code, null);
  assert.ok(rec.codeHash && !rec.codeHash.includes(code));
});

test("correct code verifies", async () => {
  const { env, mails } = makeEnv();
  await register(env, "b@x.com");
  const r = await worker.fetch(post("/v1/verify", { email: "b@x.com", code: lastCode(mails) }), env);
  assert.equal(r.status, 200);
  assert.ok((await r.json()).verify_token);
});

test("5 wrong tries burn the code, even the right code then fails", async () => {
  const { env, mails } = makeEnv();
  await register(env, "c@x.com");
  const good = lastCode(mails);
  const wrong = good === "000000" ? "111111" : "000000";
  const statuses = [];
  for (let i = 0; i < 5; i++) statuses.push((await worker.fetch(post("/v1/verify", { email: "c@x.com", code: wrong }), env)).status);
  assert.deepEqual(statuses, [400, 400, 400, 400, 429]);
  const r = await worker.fetch(post("/v1/verify", { email: "c@x.com", code: good }), env);
  assert.notEqual(r.status, 200);
  // A new code works again.
  await register(env, "c@x.com");
  const r2 = await worker.fetch(post("/v1/verify", { email: "c@x.com", code: lastCode(mails) }), env);
  assert.equal(r2.status, 200);
});

test("per-IP limit on register across many emails", async () => {
  const { env } = makeEnv();
  let last;
  for (let i = 0; i < 11; i++) last = await register(env, `u${i}@x.com`, "9.9.9.9");
  assert.equal(last.status, 429);
  assert.equal((await register(env, "other@x.com", "8.8.8.8")).status, 200);
});

test("per-IP limit on verify", async () => {
  const { env } = makeEnv();
  let last;
  for (let i = 0; i < 21; i++) last = await worker.fetch(post("/v1/verify", { email: `v${i}@x.com`, code: "123456" }, "7.7.7.7"), env);
  assert.equal(last.status, 429);
});

test("per-IP limit on activate", async () => {
  const { env } = makeEnv();
  let last;
  for (let i = 0; i < 31; i++) last = await worker.fetch(post("/v1/activate", { key: "ORBIT-AAAA-BBBB-CCCC-DDD" + (i % 10) }, "6.6.6.6"), env);
  assert.equal(last.status, 429);
});

test("unhandled errors do not leak messages", async () => {
  const { env } = makeEnv();
  env.KV.get = async () => { throw new Error("secret internal detail"); };
  const r = await worker.fetch(post("/v1/verify", { email: "z@x.com", code: "123456" }), env);
  assert.equal(r.status, 500);
  assert.ok(!(await r.text()).includes("secret internal detail"));
});
