import { useEffect, useId, useRef, useState, type FormEvent } from 'react';

type Props = {
  email: string;
  privacyHref: string;
};

const TOPICS: Array<[string, string]> = [
  ['general', 'General question'],
  ['bug', 'Bug report'],
  ['idea', 'Feature idea'],
  ['press', 'Press'],
  ['security', 'Security'],
];

const MAX_MESSAGE = 5000;

/**
 * Sends a message to Orion's inbox through /api/contact (a Vercel Function).
 * If the form can't send, it offers the plain email address instead.
 */
export default function ContactForm({ email, privacyHref }: Props) {
  const id = useId();
  const startedAt = useRef(Date.now());
  const statusRef = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle');
  const [error, setError] = useState('');
  const [fallback, setFallback] = useState(false);
  const [messageLength, setMessageLength] = useState(0);

  useEffect(() => {
    // Preselect a topic from ?topic=bug links.
    const topic = new URLSearchParams(window.location.search).get('topic');
    const select = document.getElementById(`${id}-topic`) as HTMLSelectElement | null;
    if (select && topic && TOPICS.some(([value]) => value === topic)) select.value = topic;
  }, [id]);

  useEffect(() => {
    if (state === 'sent' || state === 'error') statusRef.current?.focus();
  }, [state]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.reportValidity()) return;
    const data = Object.fromEntries(new FormData(form).entries());
    setState('sending');
    setError('');
    setFallback(false);
    try {
      const res = await fetch('/api/contact', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...data, startedAt: startedAt.current }),
      });
      const result = (await res.json().catch(() => ({}))) as { ok?: boolean; error?: string; fallback?: boolean };
      if (res.ok && result.ok) {
        form.reset();
        setMessageLength(0);
        setState('sent');
        return;
      }
      setError(result.error || 'Your message couldn’t be sent right now.');
      setFallback(result.fallback ?? res.status >= 500);
      setState('error');
    } catch {
      setError('Your message couldn’t be sent. Check your connection and try again.');
      setFallback(true);
      setState('error');
    }
  }

  if (state === 'sent') {
    return (
      <div ref={statusRef} tabIndex={-1} role="status" className="panel p-6 outline-none sm:p-8">
        <p className="eyebrow">Message sent</p>
        <h2 className="mt-3 text-2xl font-semibold text-white">Thanks, it’s on its way.</h2>
        <p className="mt-2 text-[var(--color-muted)]">We’ll reply to the email address you gave, usually within a few days.</p>
        <button type="button" className="btn btn-ghost mt-6" onClick={() => setState('idle')}>
          Send another message
        </button>
      </div>
    );
  }

  const field =
    'mt-2 w-full rounded-xl border border-[var(--color-line)] bg-[rgb(3_9_22/0.7)] px-4 py-3 text-[0.97rem] text-white placeholder:text-[var(--color-faint)] transition-colors focus:border-[var(--color-cyan)] focus:outline-none focus:ring-2 focus:ring-[rgb(56_189_248/0.25)]';
  const label = 'text-sm font-medium text-[var(--color-text)]';

  return (
    <form onSubmit={submit} noValidate={false} className="panel p-6 sm:p-8" aria-describedby={`${id}-note`}>
      <div className="grid gap-5 sm:grid-cols-2">
        <div>
          <label htmlFor={`${id}-name`} className={label}>
            Your name
          </label>
          <input id={`${id}-name`} name="name" type="text" required maxLength={80} autoComplete="name" className={field} />
        </div>
        <div>
          <label htmlFor={`${id}-email`} className={label}>
            Your email
          </label>
          <input id={`${id}-email`} name="email" type="email" required maxLength={254} autoComplete="email" placeholder="So we can reply" className={field} />
        </div>
      </div>

      <div className="mt-5">
        <label htmlFor={`${id}-topic`} className={label}>
          What’s it about?
        </label>
        <select id={`${id}-topic`} name="topic" defaultValue="general" className={field}>
          {TOPICS.map(([value, text]) => (
            <option key={value} value={value} className="bg-[#060e22]">
              {text}
            </option>
          ))}
        </select>
      </div>

      <div className="mt-5">
        <div className="flex items-baseline justify-between gap-3">
          <label htmlFor={`${id}-message`} className={label}>
            Message
          </label>
          <span className="text-xs text-[var(--color-faint)]" aria-hidden="true">
            {messageLength}/{MAX_MESSAGE}
          </span>
        </div>
        <textarea
          id={`${id}-message`}
          name="message"
          required
          minLength={10}
          maxLength={MAX_MESSAGE}
          rows={6}
          onChange={(e) => setMessageLength(e.target.value.length)}
          placeholder="For bugs: what you did, what happened, and your Windows version."
          className={`${field} resize-y`}
        />
      </div>

      {/* Honeypot for bots: hidden from people and screen readers. */}
      <div aria-hidden="true" className="absolute left-[-10000px] top-auto h-px w-px overflow-hidden">
        <label htmlFor={`${id}-website`}>Leave this empty</label>
        <input id={`${id}-website`} name="website" type="text" tabIndex={-1} autoComplete="off" />
      </div>

      {state === 'error' && (
        <div ref={statusRef} tabIndex={-1} role="alert" className="mt-5 rounded-xl border border-[rgb(248_113_113/0.4)] bg-[rgb(127_29_29/0.2)] p-4 text-sm text-[#fecaca] outline-none">
          {error}
          {fallback && (
            <>
              {' '}
              You can email us directly at{' '}
              <a className="font-medium text-white underline" href={`mailto:${email}`}>
                {email}
              </a>
              .
            </>
          )}
        </div>
      )}

      <div className="mt-6 flex flex-wrap items-center justify-between gap-4">
        <p id={`${id}-note`} className="max-w-sm text-xs leading-relaxed text-[var(--color-faint)]">
          Your name, email and message are sent to Orion’s inbox and used only to reply. Please don’t include passwords or keys.{' '}
          <a className="underline" href={privacyHref}>
            Privacy
          </a>
        </p>
        <button type="submit" className="btn btn-primary" disabled={state === 'sending'}>
          {state === 'sending' ? 'Sending…' : 'Send message'}
        </button>
      </div>
    </form>
  );
}
