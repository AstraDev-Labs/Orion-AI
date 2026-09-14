import { useEffect, useRef, useState } from 'react';
import { startCouncilRun, fetchCouncilStatus, type CouncilRun } from '../api';

const STATUS_COLOR: Record<string, string> = {
  pending: 'var(--color-neutral-600)',
  running: 'var(--color-accent-300)',
  done: 'var(--color-accent-300)',
  error: '#e06b5c',
};

/**
 * The Council — fans a directive out to every engine that actually passes a
 * health check right now (see POST /v1/council/run). With only Ollama
 * configured, this honestly shows a single seat -- that's correct, not a bug.
 */
export function CouncilScreen() {
  const [directive, setDirective] = useState('');
  const [run, setRun] = useState<CouncilRun | null>(null);
  const [error, setError] = useState('');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current);
  }, []);

  const start = async () => {
    if (!directive.trim()) return;
    setError('');
    try {
      const { run_id } = await startCouncilRun(directive.trim());
      const poll = async () => {
        try {
          const r = await fetchCouncilStatus(run_id);
          setRun(r);
          if (r.status === 'complete' || r.status === 'error') {
            if (pollRef.current) clearInterval(pollRef.current);
          }
        } catch {
          /* keep polling; a transient miss is not fatal */
        }
      };
      poll();
      pollRef.current = setInterval(poll, 1200);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start');
    }
  };

  return (
    <div className="holo-panel holo-boot-in" style={{ position: 'absolute', inset: 0, overflowY: 'auto', padding: '20px 30px 24px' }}>
      <div className="holo-corner holo-corner-tl" />
      <div className="holo-corner holo-corner-br" />
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          justifyContent: 'space-between',
          paddingBottom: 13,
          borderBottom: '1px solid rgba(182,130,53,0.26)',
          marginBottom: 18,
        }}
      >
        <div>
          <div className="holo-kicker" style={{ marginBottom: 5 }}>
            Multi-model working · 07
          </div>
          <h2 style={{ fontSize: 26 }}>The Council</h2>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 10, marginBottom: 20 }}>
        <div
          className="holo-panel"
          style={{ flex: 1, display: 'flex', alignItems: 'center', padding: '11px 14px', borderColor: 'rgba(182,130,53,0.44)' }}
        >
          <input
            value={directive}
            onChange={(e) => setDirective(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && start()}
            placeholder="Name a directive for every seated model…"
            style={{ flex: 1, background: 'transparent', border: 0, outline: 'none', fontSize: 14, color: 'var(--color-neutral-100)' }}
          />
        </div>
        <button className="holo-ghost-btn" onClick={start} disabled={!directive.trim() || run?.status === 'running'}>
          Convene
        </button>
      </div>

      {error && <div style={{ color: '#e06b5c', fontSize: 12, marginBottom: 12 }}>{error}</div>}

      {!run && !error && (
        <div style={{ color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>
          No session yet. Only engines that pass a live health check are seated — with just Ollama configured, expect one
          seat until cloud keys are added.
        </div>
      )}

      {run && (
        <>
          {run.directive && (
            <div style={{ borderLeft: '2px solid var(--color-accent)', padding: '2px 0 2px 15px', marginBottom: 20 }}>
              <div className="holo-kicker" style={{ marginBottom: 5 }}>
                Directive under deliberation
              </div>
              <p style={{ margin: 0, fontSize: 14.5, lineHeight: 1.6, fontStyle: 'italic' }}>{run.directive}</p>
            </div>
          )}

          {run.seats.length === 0 && run.status !== 'starting' && (
            <div style={{ color: '#e06b5c', fontSize: 12.5 }}>
              No engine passed a health check. Nothing was run — this reflects your actual configuration, not an error.
            </div>
          )}

          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, marginBottom: 22 }}>
            <tbody>
              {run.seats.map((s) => (
                <tr key={s.key}>
                  <td style={{ padding: '12px 10px 12px 0', borderBottom: '1px solid rgba(248,244,244,0.08)', verticalAlign: 'top' }}>
                    <div style={{ fontFamily: 'var(--font-heading)', fontSize: 19 }}>{s.name}</div>
                  </td>
                  <td style={{ padding: '12px 10px', borderBottom: '1px solid rgba(248,244,244,0.08)', verticalAlign: 'top' }}>
                    <span style={{ fontSize: 9.5, letterSpacing: '0.16em', textTransform: 'uppercase', color: STATUS_COLOR[s.status] }}>
                      {s.status}
                    </span>
                  </td>
                  <td
                    style={{
                      padding: '12px 10px',
                      borderBottom: '1px solid rgba(248,244,244,0.08)',
                      textAlign: 'right',
                      color: 'var(--color-neutral-400)',
                    }}
                  >
                    {s.tokens} tokens
                  </td>
                  <td
                    style={{
                      padding: '12px 0 12px 10px',
                      borderBottom: '1px solid rgba(248,244,244,0.08)',
                      textAlign: 'right',
                      color: 'var(--color-neutral-600)',
                    }}
                  >
                    {s.elapsed_s !== undefined ? `${s.elapsed_s}s` : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {run.status === 'complete' && (
            <div style={{ border: '1px solid rgba(182,130,53,0.28)', padding: '15px 16px' }}>
              <div className="holo-kicker" style={{ marginBottom: 10 }}>
                Concord
              </div>
              {run.concord != null ? (
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
                  <span style={{ fontFamily: 'var(--font-heading)', fontWeight: 300, fontSize: 36, color: 'var(--color-accent-300)' }}>
                    {run.concord}%
                  </span>
                  <span style={{ fontSize: 11, color: 'var(--color-neutral-400)', fontStyle: 'italic' }}>
                    mean embedding similarity across {run.seats.length} seats
                  </span>
                </div>
              ) : (
                <p style={{ margin: 0, fontSize: 12.5, color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>
                  Concord needs at least two seated models to compare — only one is configured right now.
                </p>
              )}
              {run.seats.map(
                (s) =>
                  s.text && (
                    <div key={s.key} style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid rgba(248,244,244,0.08)' }}>
                      <div className="holo-kicker" style={{ marginBottom: 4 }}>
                        {s.name}
                      </div>
                      <p style={{ margin: 0, fontSize: 12.5, lineHeight: 1.6, color: 'var(--color-neutral-300)' }}>{s.text}</p>
                    </div>
                  ),
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default CouncilScreen;
