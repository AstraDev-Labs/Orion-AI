import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  authorizeConnection,
  disconnectConnection,
  fetchConnections,
  restartBackend,
  saveConnection,
  verifyConnection,
  type Connection,
} from '../api';
import { WhatsAppConnectPanel } from './GovernanceScreen';

const CATEGORY_ORDER = ['Messaging & email', 'Knowledge & search', 'Accounts', 'Optional cloud AI'];

type Notice = { ok: boolean; text: string } | null;

const inputStyle: React.CSSProperties = {
  flex: 1,
  minWidth: 0,
  background: 'transparent',
  border: '1px solid rgba(182,130,53,0.34)',
  padding: '8px 11px',
  fontSize: 13,
  color: 'var(--color-neutral-100)',
  fontFamily: 'var(--font-body)',
};

function StatusPill({ conn }: { conn: Connection }) {
  const waiting = conn.oauth?.state === 'waiting';
  const label = conn.status === 'coming_soon'
    ? 'Work in progress'
    : waiting
    ? 'Signing in…'
    : conn.status === 'connected'
      ? '● Live'
      : conn.status === 'configured'
        ? 'Credentials saved'
      : conn.status === 'ready'
        ? 'Ready to sign in'
        : 'Not connected';
  const color =
    conn.status === 'connected' ? 'var(--color-accent-300)' : conn.status === 'configured' || waiting || conn.status === 'ready' ? 'var(--color-accent-400)' : 'var(--color-neutral-600)';
  return (
    <span style={{ flexShrink: 0, fontSize: 9.5, letterSpacing: '0.14em', textTransform: 'uppercase', color }}>{label}</span>
  );
}

function ConnectionCard({
  conn,
  onChanged,
  onRestartNeeded,
}: {
  conn: Connection;
  onChanged: (next?: Connection) => void;
  onRestartNeeded: () => void;
}) {
  const [open, setOpen] = useState(false);
  // A connected card shows a summary; the form only appears on "Change".
  const [editing, setEditing] = useState(false);
  const [ownClient, setOwnClient] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const [reveal, setReveal] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState<'' | 'save' | 'verify' | 'disconnect' | 'authorize'>('');
  const [notice, setNotice] = useState<Notice>(null);

  // Non-secret fields start from their stored value; secrets start empty and
  // keep the stored value unless something new is typed.
  useEffect(() => {
    if (!open) return;
    setValues(Object.fromEntries(conn.fields.map((f) => [f.key, f.secret ? '' : f.value])));
  }, [open, conn.fields]);

  useEffect(() => {
    if (!open) {
      setEditing(false);
      setOwnClient(false);
      setNotice(null);
    }
  }, [open]);

  const run = async (kind: typeof busy, fn: () => Promise<void>) => {
    setBusy(kind);
    setNotice(null);
    try {
      await fn();
    } catch (e) {
      setNotice({ ok: false, text: e instanceof Error ? e.message : 'Something went wrong' });
    } finally {
      setBusy('');
    }
  };

  const save = () =>
    run('save', async () => {
      const res = await saveConnection(conn.id, values);
      setNotice({ ok: res.ok, text: res.message });
      if (res.saved) {
        setEditing(false);
        onChanged(res.connection);
        if (conn.restart_required) onRestartNeeded();
      }
    });

  const verify = () =>
    run('verify', async () => {
      const res = await verifyConnection(conn.id);
      setNotice({ ok: res.ok, text: res.message });
    });

  const disconnect = () =>
    run('disconnect', async () => {
      if (!window.confirm(`Disconnect ${conn.name}? Its saved keys are removed from this computer.`)) return;
      const res = await disconnectConnection(conn.id);
      setNotice({ ok: true, text: res.message });
      setValues({});
      onChanged(res.connection);
      if (conn.restart_required) onRestartNeeded();
    });

  const authorize = () =>
    run('authorize', async () => {
      const res = await authorizeConnection(conn.id);
      setNotice({ ok: true, text: res.message });
      onChanged();
    });

  const connected = conn.status === 'connected';
  const configured = connected || conn.status === 'configured';
  const showForm = !configured || editing;
  // The first non-secret value identifies the account ("you@gmail.com").
  const identity = conn.fields.find((f) => !f.secret && f.value)?.value;
  const requiredMissing = conn.fields.some((f) => f.required && !f.set && !(values[f.key] || '').trim());

  return (
    <div style={{ borderBottom: '1px solid rgba(248,244,244,0.08)' }}>
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 18,
          padding: '12px 0',
          background: 'transparent',
          border: 0,
          cursor: 'pointer',
          textAlign: 'left',
          color: 'inherit',
        }}
        aria-expanded={open}
      >
        <div style={{ minWidth: 0 }}>
          <div style={{ fontFamily: 'var(--font-heading)', fontSize: 18 }}>
            {conn.name}
            {conn.cloud && (
              <span
                title="Using this sends requests to an online service"
                style={{ marginLeft: 9, fontSize: 9, letterSpacing: '0.14em', textTransform: 'uppercase', color: '#d89a5b' }}
              >
                cloud
              </span>
            )}
          </div>
          <div style={{ fontSize: 11, color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>{conn.unlocks}</div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
          <StatusPill conn={conn} />
          <span style={{ color: 'var(--color-neutral-600)', fontSize: 12 }}>{open ? '−' : '+'}</span>
        </div>
      </button>

      {open && conn.status === 'coming_soon' && (
        <div style={{ padding: '2px 0 16px', fontSize: 12.5, lineHeight: 1.6, color: 'var(--color-neutral-400)' }}>
          {conn.coming_soon}
        </div>
      )}

      {open && conn.status !== 'coming_soon' && conn.kind === 'whatsapp' && (
        <div style={{ paddingBottom: 14 }}>
          <WhatsAppConnectPanel />
        </div>
      )}

      {open && conn.status !== 'coming_soon' && conn.kind !== 'whatsapp' && !showForm && (
        <div style={{ padding: '2px 0 16px', display: 'flex', flexDirection: 'column', gap: 11 }}>
          <div style={{ fontSize: 13, color: 'var(--color-neutral-300)' }}>
            {identity ? (
              <>
              {connected ? 'Live as ' : 'Credentials saved for '}
              <span style={{ color: 'var(--color-accent-300)' }}>{identity}</span>
            </>
          ) : (
            connected
              ? 'The provider runtime is connected. Saved keys are kept on this computer and never shown again.'
              : 'Credentials are saved on this computer. This does not by itself confirm the provider is online.'
          )}
          </div>
          {!!conn.capabilities?.length && (
            <div style={{ fontSize: 12, color: 'var(--color-neutral-500)' }}>
              Orion actions: {conn.capabilities.join(' · ')}
            </div>
          )}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {conn.can_verify && (
              <button type="button" className="holo-ghost-btn" onClick={() => void verify()} disabled={!!busy}>
                {busy === 'verify' ? 'Checking…' : 'Test'}
              </button>
            )}
            {conn.kind === 'oauth' && (
              <button type="button" className="holo-ghost-btn" onClick={() => void authorize()} disabled={!!busy}>
                Sign in again
              </button>
            )}
            <button type="button" className="holo-ghost-btn" onClick={() => setEditing(true)} disabled={!!busy}>
              Change
            </button>
            <button
              type="button"
              onClick={() => void disconnect()}
              disabled={!!busy}
              style={{
                background: 'transparent',
                border: '1px solid rgba(224,107,92,0.4)',
                color: '#e06b5c',
                cursor: 'pointer',
                padding: '5px 12px',
                fontSize: 11,
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
              }}
            >
              {busy === 'disconnect' ? 'Removing…' : 'Disconnect'}
            </button>
          </div>
          {notice && (
            <div role="status" style={{ fontSize: 12, color: notice.ok ? 'var(--color-accent-300)' : '#e06b5c' }}>
              {notice.text}
            </div>
          )}
        </div>
      )}

      {open && conn.status !== 'coming_soon' && conn.kind === 'oauth' && conn.one_click && showForm && !ownClient && (
        <div style={{ padding: '2px 0 16px', display: 'flex', flexDirection: 'column', gap: 11 }}>
          <div style={{ fontSize: 12.5, color: 'var(--color-neutral-400)', lineHeight: 1.6 }}>
            A browser window opens where you choose your Google account and allow access. Your
            sign-in stays on this computer.
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
            <button
              type="button"
              className="holo-ghost-btn"
              onClick={() => void authorize()}
              disabled={!!busy || conn.oauth?.state === 'waiting'}
              style={{ fontSize: 13, padding: '8px 18px' }}
            >
              {conn.oauth?.state === 'waiting' ? 'Waiting for browser…' : 'Sign in with Google'}
            </button>
            <button
              type="button"
              onClick={() => setOwnClient(true)}
              style={{
                background: 'transparent',
                border: 0,
                color: 'var(--color-neutral-600)',
                cursor: 'pointer',
                fontSize: 11.5,
                textDecoration: 'underline',
              }}
            >
              Use my own OAuth client (advanced)
            </button>
          </div>
          {(notice || conn.oauth?.message) && (
            <div
              role="status"
              style={{
                fontSize: 12,
                color: (notice ? notice.ok : conn.oauth?.state !== 'error') ? 'var(--color-accent-300)' : '#e06b5c',
              }}
            >
              {notice ? notice.text : conn.oauth?.message}
            </div>
          )}
        </div>
      )}

      {open && conn.status !== 'coming_soon' && conn.kind !== 'whatsapp' && showForm && !(conn.kind === 'oauth' && conn.one_click && !ownClient) && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
          style={{ padding: '2px 0 16px', display: 'flex', flexDirection: 'column', gap: 11 }}
        >
          {(conn.setup_steps || conn.setup_url) && (
            <div style={{ fontSize: 12, lineHeight: 1.6, color: 'var(--color-neutral-400)' }}>
              {conn.setup_steps}{' '}
              {conn.setup_url && (
                <a href={conn.setup_url} target="_blank" rel="noreferrer" style={{ color: 'var(--color-accent-300)' }}>
                  Open setup page ↗
                </a>
              )}
            </div>
          )}

          {conn.fields.map((f) => (
            <label key={f.key} style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              <span style={{ fontSize: 10, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'var(--color-neutral-400)' }}>
                {f.label}
                {!f.required && <span style={{ color: 'var(--color-neutral-600)' }}> · optional</span>}
                {f.secret && f.set && <span style={{ color: 'var(--color-accent-300)' }}> · saved</span>}
              </span>
              <div style={{ display: 'flex', gap: 6 }}>
                <input
                  type={f.secret && !reveal[f.key] ? 'password' : 'text'}
                  autoComplete="off"
                  spellCheck={false}
                  value={values[f.key] ?? ''}
                  placeholder={f.secret && f.set ? 'Saved — type to replace' : f.placeholder}
                  onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                  style={inputStyle}
                />
                {f.secret && (
                  <button
                    type="button"
                    className="holo-ghost-btn"
                    onClick={() => setReveal((r) => ({ ...r, [f.key]: !r[f.key] }))}
                    style={{ fontSize: 10 }}
                  >
                    {reveal[f.key] ? 'Hide' : 'Show'}
                  </button>
                )}
              </div>
              {f.help && <span style={{ fontSize: 11, color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>{f.help}</span>}
            </label>
          ))}

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 2 }}>
            <button type="submit" className="holo-ghost-btn" disabled={!!busy || requiredMissing}>
              {busy === 'save' ? (conn.can_verify ? 'Checking…' : 'Saving…') : conn.can_verify ? 'Save & verify' : 'Save'}
            </button>
            {conn.kind === 'oauth' && (
              <button
                type="button"
                className="holo-ghost-btn"
                onClick={() => void authorize()}
                disabled={!!busy || conn.status === 'not_connected' || conn.oauth?.state === 'waiting'}
              >
                {conn.oauth?.state === 'waiting' ? 'Waiting for browser…' : connected ? 'Sign in again' : 'Sign in'}
              </button>
            )}
            {configured && (
              <button type="button" className="holo-ghost-btn" onClick={() => setEditing(false)} disabled={!!busy}>
                Cancel
              </button>
            )}
            {!configured && conn.status === 'ready' && (
              <button
                type="button"
                onClick={() => void disconnect()}
                disabled={!!busy}
                style={{
                  background: 'transparent',
                  border: '1px solid rgba(224,107,92,0.4)',
                  color: '#e06b5c',
                  cursor: 'pointer',
                  padding: '5px 12px',
                  fontSize: 11,
                  letterSpacing: '0.08em',
                  textTransform: 'uppercase',
                }}
              >
                {busy === 'disconnect' ? 'Removing…' : 'Disconnect'}
              </button>
            )}
          </div>

          {(notice || conn.oauth?.message) && (
            <div
              role="status"
              style={{
                fontSize: 12,
                color: (notice ? notice.ok : conn.oauth?.state !== 'error') ? 'var(--color-accent-300)' : '#e06b5c',
              }}
            >
              {notice ? notice.text : conn.oauth?.message}
            </div>
          )}
        </form>
      )}
    </div>
  );
}

/** Connections — link the accounts, keys and services Orion's features need. */
export function ConnectionsScreen() {
  const [items, setItems] = useState<Connection[] | null>(null);
  const [error, setError] = useState('');
  const [restartNeeded, setRestartNeeded] = useState(false);
  const [restarting, setRestarting] = useState(false);

  const load = useCallback(
    () =>
      fetchConnections()
        .then((d) => {
          setItems(d.connections);
          setError('');
        })
        .catch((e) => setError(e instanceof Error ? e.message : 'Could not load connections')),
    [],
  );

  useEffect(() => {
    void load();
  }, [load]);

  // Poll only while a browser sign-in is in progress.
  const waiting = items?.some((c) => c.oauth?.state === 'waiting');
  useEffect(() => {
    if (!waiting) return;
    const id = setInterval(() => void load(), 2500);
    return () => clearInterval(id);
  }, [waiting, load]);

  const onChanged = (next?: Connection) => {
    if (next) setItems((prev) => prev?.map((c) => (c.id === next.id ? next : c)) ?? prev);
    else void load();
  };

  const grouped = useMemo(() => {
    const groups = new Map<string, Connection[]>();
    for (const c of items ?? []) groups.set(c.category, [...(groups.get(c.category) ?? []), c]);
    return [...groups.entries()].sort(
      (a, b) => (CATEGORY_ORDER.indexOf(a[0]) + 99) % 99 - (CATEGORY_ORDER.indexOf(b[0]) + 99) % 99,
    );
  }, [items]);

  const configuredCount = items?.filter((c) => c.status === 'connected' || c.status === 'configured').length ?? 0;
  const liveCount = items?.filter((c) => c.status === 'connected').length ?? 0;

  const restart = async () => {
    setRestarting(true);
    try {
      await restartBackend();
      setRestartNeeded(false);
      setTimeout(() => void load(), 8000);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Restart failed');
    } finally {
      setRestarting(false);
    }
  };

  return (
    <div className="holo-panel holo-boot-in" style={{ position: 'absolute', inset: 0, overflowY: 'auto', padding: '20px 30px 24px' }}>
      <div className="holo-corner holo-corner-tl" />
      <div className="holo-corner holo-corner-br" />
      <div style={{ paddingBottom: 13, borderBottom: '1px solid rgba(182,130,53,0.26)', marginBottom: 16 }}>
        <div className="holo-kicker" style={{ marginBottom: 5, display: 'flex', justifyContent: 'space-between' }}>
          <span>Conduits · 12</span>
          {items && (
            <span style={{ color: 'var(--color-accent-300)' }}>
              {configuredCount} / {items.length} configured · {liveCount} live
            </span>
          )}
        </div>
        <h2 style={{ fontSize: 26 }}>Connections</h2>
        <p style={{ margin: '6px 0 0', fontSize: 12, color: 'var(--color-neutral-600)', fontStyle: 'italic', maxWidth: 640 }}>
          Link the accounts and keys that Orion's features use. Everything is stored only on this computer
          (~/.orion), and saved secrets are never shown again.
        </p>
      </div>

      {restartNeeded && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 14,
            maxWidth: 640,
            padding: '10px 13px',
            marginBottom: 14,
            border: '1px solid rgba(182,130,53,0.5)',
            fontSize: 12.5,
          }}
        >
          <span>Some changes take effect after Orion restarts.</span>
          <button className="holo-ghost-btn" onClick={() => void restart()} disabled={restarting}>
            {restarting ? 'Restarting…' : 'Restart now'}
          </button>
        </div>
      )}

      {error && <div style={{ color: '#e06b5c', fontSize: 12, marginBottom: 12 }}>{error}</div>}
      {!items && !error && <div style={{ color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>Reading…</div>}

      <div style={{ maxWidth: 640 }}>
        {grouped.map(([category, conns]) => (
          <section key={category} style={{ marginBottom: 22 }}>
            <h3
              style={{
                fontSize: 11,
                fontWeight: 500,
                letterSpacing: '0.2em',
                textTransform: 'uppercase',
                color: 'var(--color-neutral-600)',
                margin: '8px 0 4px',
              }}
            >
              {category}
            </h3>
            {conns.map((c) => (
              <ConnectionCard key={c.id} conn={c} onChanged={onChanged} onRestartNeeded={() => setRestartNeeded(true)} />
            ))}
          </section>
        ))}
      </div>
    </div>
  );
}

export default ConnectionsScreen;
