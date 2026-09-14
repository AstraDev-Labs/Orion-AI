// Contact form logic, kept free of mail and platform code so it can be tested.
// Vercel ignores files under api/ whose path starts with an underscore.

export const TOPICS = {
  general: 'General question',
  bug: 'Bug report',
  idea: 'Feature idea',
  press: 'Press',
  security: 'Security',
};

export const LIMITS = { name: 80, email: 254, message: 5000, minMessage: 10 };

/** A human needs a few seconds to fill the form in; bots post instantly. */
const MIN_FILL_MS = 3000;
/** Forms left open longer than this are treated as stale. */
const MAX_FILL_MS = 24 * 60 * 60 * 1000;

const RATE_WINDOW_MS = 10 * 60 * 1000;
const RATE_MAX = 5;

const EMAIL = /^[^\s@<>()[\]\\,;:"]+@[^\s@<>()[\]\\,;:"]+\.[^\s@<>()[\]\\,;:"]{2,}$/;

/** Collapse whitespace and control characters so values are safe in headers. */
function oneLine(value) {
  return String(value ?? '')
    .replace(/[\u0000-\u001f\u007f\u2028\u2029]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

/** Keep line breaks in the message body, drop other control characters. */
function multiLine(value) {
  return String(value ?? '')
    .replace(/\r\n?/g, '\n')
    .replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, '')
    .trim();
}

/**
 * Check a submission. Returns `{ ok: true, value }`, `{ ok: false, error }`
 * for mistakes the visitor can fix, or `{ ok: false, spam: true }` for
 * submissions that should be silently dropped.
 */
export function validateSubmission(body, now = Date.now()) {
  if (!body || typeof body !== 'object') return { ok: false, error: 'The form could not be read. Please try again.' };

  // Honeypot: a hidden field real visitors never see or fill in.
  if (oneLine(body.website)) return { ok: false, spam: true };

  const startedAt = Number(body.startedAt);
  if (!Number.isFinite(startedAt) || now - startedAt < MIN_FILL_MS || now - startedAt > MAX_FILL_MS) {
    return { ok: false, spam: true };
  }

  const name = oneLine(body.name);
  const email = oneLine(body.email).toLowerCase();
  const topic = Object.hasOwn(TOPICS, body.topic) ? body.topic : 'general';
  const message = multiLine(body.message);

  if (!name) return { ok: false, error: 'Please enter your name.' };
  if (name.length > LIMITS.name) return { ok: false, error: `Please keep your name under ${LIMITS.name} characters.` };
  if (!email || email.length > LIMITS.email || !EMAIL.test(email)) {
    return { ok: false, error: 'Please enter a valid email address so we can reply.' };
  }
  if (message.length < LIMITS.minMessage) return { ok: false, error: 'Please write a little more in your message.' };
  if (message.length > LIMITS.message) {
    return { ok: false, error: `Please keep your message under ${LIMITS.message} characters.` };
  }

  return { ok: true, value: { name, email, topic, message } };
}

/**
 * The email sent to Orion's inbox. It is sent from Orion's own account, with
 * the visitor as Reply-To, so nothing is sent "as" the visitor and no mail
 * ever goes to the address they typed.
 */
export function buildMail(submission, { from, to }, meta = {}) {
  const { name, email, topic, message } = submission;
  const subjectName = name.length > 40 ? `${name.slice(0, 40)}…` : name;
  const lines = [
    message,
    '',
    '—',
    `From: ${name} <${email}>`,
    `Topic: ${TOPICS[topic]}`,
    meta.page ? `Sent from: ${oneLine(meta.page).slice(0, 200)}` : null,
    'Reply to this email to answer them.',
  ].filter((line) => line !== null);
  return {
    from: { name: 'Orion website', address: from },
    to,
    replyTo: { name, address: email },
    subject: `[Orion website] ${TOPICS[topic]} from ${subjectName}`,
    text: lines.join('\n'),
  };
}

/** Best-effort per-instance rate limit; serverless instances don't share it. */
export function createRateLimiter({ windowMs = RATE_WINDOW_MS, max = RATE_MAX } = {}) {
  const hits = new Map();
  return function allow(key, now = Date.now()) {
    const recent = (hits.get(key) ?? []).filter((t) => now - t < windowMs);
    if (recent.length >= max) {
      hits.set(key, recent);
      return false;
    }
    recent.push(now);
    hits.set(key, recent);
    if (hits.size > 5000) hits.delete(hits.keys().next().value);
    return true;
  };
}

const json = (status, data) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' },
  });

/**
 * Builds the POST handler. `sendMail(mail)` delivers a message; `env` holds
 * CONTACT_SMTP_USER, CONTACT_SMTP_PASS and optionally CONTACT_TO.
 */
export function createContactHandler({ sendMail, env, now = () => Date.now(), allow = createRateLimiter() }) {
  return async function POST(request) {
    const origin = request.headers.get('origin');
    const host = request.headers.get('x-forwarded-host') || request.headers.get('host');
    if (origin && host) {
      let originHost = '';
      try {
        originHost = new URL(origin).host;
      } catch {
        /* malformed origin */
      }
      if (originHost !== host) return json(403, { ok: false, error: 'Please send the form from the Orion website.' });
    }

    if (!(request.headers.get('content-type') || '').includes('application/json')) {
      return json(415, { ok: false, error: 'The form could not be read. Please try again.' });
    }

    const raw = await request.text();
    if (raw.length > 20000) return json(413, { ok: false, error: 'That message is too long.' });

    let body;
    try {
      body = JSON.parse(raw);
    } catch {
      return json(400, { ok: false, error: 'The form could not be read. Please try again.' });
    }

    const ip = (request.headers.get('x-forwarded-for') || '').split(',')[0].trim() || 'unknown';
    if (!allow(ip, now())) {
      return json(429, { ok: false, error: 'Too many messages from your connection. Please try again in a few minutes.' });
    }

    const result = validateSubmission(body, now());
    // Pretend spam succeeded so bots learn nothing.
    if (result.spam) return json(200, { ok: true });
    if (!result.ok) return json(400, { ok: false, error: result.error });

    const from = env.CONTACT_SMTP_USER;
    if (!from || !env.CONTACT_SMTP_PASS) {
      return json(503, { ok: false, error: 'The contact form isn’t set up yet.', fallback: true });
    }

    try {
      await sendMail(buildMail(result.value, { from, to: env.CONTACT_TO || from }, { page: request.headers.get('referer') }));
    } catch (error) {
      console.error('contact: sending failed', error instanceof Error ? error.message : error);
      return json(502, { ok: false, error: 'Your message couldn’t be sent right now.', fallback: true });
    }
    return json(200, { ok: true });
  };
}
