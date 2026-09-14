import assert from 'node:assert/strict';
import { test } from 'node:test';
import { buildMail, createContactHandler, createRateLimiter, validateSubmission } from '../api/_lib/contact.js';

const NOW = 1_800_000_000_000;
const good = { name: 'Asha', email: 'Asha@Example.com', topic: 'bug', message: 'Voice stops after a minute.', startedAt: NOW - 20_000, website: '' };
const env = { CONTACT_SMTP_USER: 'orion@example.com', CONTACT_SMTP_PASS: 'secret' };

function post(body, headers = {}) {
  return new Request('https://orion.example.com/api/contact', {
    method: 'POST',
    headers: { 'content-type': 'application/json', host: 'orion.example.com', origin: 'https://orion.example.com', 'x-forwarded-for': '203.0.113.9', ...headers },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  });
}

function handler(overrides = {}) {
  const sent = [];
  const POST = createContactHandler({
    sendMail: async (mail) => void sent.push(mail),
    env,
    now: () => NOW,
    allow: () => true,
    ...overrides,
  });
  return { POST, sent };
}

test('accepts a normal message and normalises the email', () => {
  const result = validateSubmission(good, NOW);
  assert.equal(result.ok, true);
  assert.equal(result.value.email, 'asha@example.com');
});

test('honeypot and instant submissions are treated as spam', () => {
  assert.equal(validateSubmission({ ...good, website: 'http://spam' }, NOW).spam, true);
  assert.equal(validateSubmission({ ...good, startedAt: NOW - 500 }, NOW).spam, true);
  assert.equal(validateSubmission({ ...good, startedAt: undefined }, NOW).spam, true);
});

test('rejects fixable mistakes with a message', () => {
  assert.match(validateSubmission({ ...good, name: '  ' }, NOW).error, /name/);
  assert.match(validateSubmission({ ...good, email: 'not-an-email' }, NOW).error, /email/);
  assert.match(validateSubmission({ ...good, message: 'hi' }, NOW).error, /more/);
  assert.match(validateSubmission({ ...good, message: 'x'.repeat(5001) }, NOW).error, /under/);
});

test('header injection is neutralised', () => {
  const result = validateSubmission({ ...good, name: 'Eve\r\nBcc: victim@example.com' }, NOW);
  assert.equal(result.ok, true);
  assert.doesNotMatch(result.value.name, /[\r\n]/);
  assert.equal(validateSubmission({ ...good, email: 'eve@example.com\nbcc:x@y.com' }, NOW).ok, false);
});

test('mail comes from Orion, replies go to the visitor, unknown topics fall back', () => {
  const { value } = validateSubmission({ ...good, topic: 'constructor' }, NOW);
  const mail = buildMail(value, { from: 'orion@example.com', to: 'orion@example.com' });
  assert.equal(mail.from.address, 'orion@example.com');
  assert.equal(mail.to, 'orion@example.com');
  assert.equal(mail.replyTo.address, 'asha@example.com');
  assert.match(mail.subject, /General question from Asha/);
  assert.match(mail.text, /Voice stops after a minute\./);
});

test('handler sends a valid message', async () => {
  const { POST, sent } = handler();
  const res = await POST(post(good));
  assert.equal(res.status, 200);
  assert.deepEqual(await res.json(), { ok: true });
  assert.equal(sent.length, 1);
  assert.equal(sent[0].replyTo.address, 'asha@example.com');
});

test('handler drops spam silently without sending', async () => {
  const { POST, sent } = handler();
  const res = await POST(post({ ...good, website: 'filled' }));
  assert.equal(res.status, 200);
  assert.equal(sent.length, 0);
});

test('handler refuses other sites, bad bodies and floods', async () => {
  const { POST, sent } = handler();
  assert.equal((await POST(post(good, { origin: 'https://evil.example' }))).status, 403);
  assert.equal((await POST(post('{not json'))).status, 400);
  assert.equal((await POST(post(good, { 'content-type': 'text/plain' }))).status, 415);
  assert.equal((await POST(post({ ...good, message: 'x'.repeat(30000) }))).status, 413);
  const limited = handler({ allow: () => false });
  assert.equal((await limited.POST(post(good))).status, 429);
  assert.equal(sent.length, 0);
});

test('handler reports missing configuration and send failures without leaking details', async () => {
  const unconfigured = handler({ env: {} });
  const res = await unconfigured.POST(post(good));
  assert.equal(res.status, 503);
  assert.equal((await res.json()).fallback, true);

  const failing = handler({
    sendMail: async () => {
      throw new Error('535 Username and Password not accepted secret');
    },
  });
  const failed = await failing.POST(post(good));
  assert.equal(failed.status, 502);
  assert.doesNotMatch(JSON.stringify(await failed.json()), /secret|535/);
});

test('rate limiter allows a burst then blocks until the window passes', () => {
  const allow = createRateLimiter({ windowMs: 1000, max: 2 });
  assert.equal(allow('ip', 0), true);
  assert.equal(allow('ip', 10), true);
  assert.equal(allow('ip', 20), false);
  assert.equal(allow('other', 20), true);
  assert.equal(allow('ip', 1500), true);
});
