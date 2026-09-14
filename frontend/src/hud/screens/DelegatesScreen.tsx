import { useEffect, useState } from 'react';
import { fetchAgents, type ManagedAgent } from '../api';

const STATUS_COLOR: Record<string, string> = {
  running: 'var(--color-accent-300)',
  idle: 'var(--color-neutral-600)',
  paused: 'var(--color-neutral-400)',
  error: '#e06b5c',
  needs_attention: '#e0b45c',
  budget_exceeded: '#e0b45c',
  stalled: '#e0b45c',
};

/** Delegates — standing agents, real data from /v1/managed-agents. */
export function DelegatesScreen() {
  const [agents, setAgents] = useState<ManagedAgent[] | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    fetchAgents()
      .then(setAgents)
      .catch((e) => setError(e.message));
  }, []);

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
            Standing orders · 03
          </div>
          <h2 style={{ fontSize: 26 }}>Delegates</h2>
        </div>
      </div>

      {error && <div style={{ color: '#e06b5c', fontSize: 12 }}>Could not reach the agent manager: {error}</div>}
      {agents === null && !error && <div style={{ color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>Reading…</div>}
      {agents !== null && agents.length === 0 && (
        <div style={{ color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>No delegates commissioned yet.</div>
      )}

      {agents && agents.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13.5 }}>
          <thead>
            <tr>
              {['Delegate', 'Condition', 'Runs', 'Cost'].map((h, i) => (
                <th
                  key={h}
                  style={{
                    textAlign: i === 2 || i === 3 ? 'right' : 'left',
                    fontWeight: 500,
                    fontSize: 9,
                    letterSpacing: '0.2em',
                    textTransform: 'uppercase',
                    color: 'var(--color-neutral-600)',
                    padding: '0 10px 8px 0',
                    borderBottom: '1px solid rgba(182,130,53,0.36)',
                  }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {agents.map((a) => (
              <tr key={a.id}>
                <td style={{ padding: '12px 10px 12px 0', borderBottom: '1px solid rgba(248,244,244,0.08)', verticalAlign: 'top' }}>
                  <div style={{ fontFamily: 'var(--font-heading)', fontSize: 19 }}>{a.name}</div>
                  <div style={{ fontSize: 11, color: 'var(--color-neutral-600)', fontStyle: 'italic', marginTop: 2 }}>
                    {a.agent_type}
                  </div>
                </td>
                <td style={{ padding: '12px 10px', borderBottom: '1px solid rgba(248,244,244,0.08)', verticalAlign: 'top' }}>
                  <span
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 7,
                      fontSize: 9.5,
                      letterSpacing: '0.16em',
                      textTransform: 'uppercase',
                      color: STATUS_COLOR[a.status] || 'var(--color-neutral-400)',
                      border: `1px solid ${STATUS_COLOR[a.status] || 'var(--color-neutral-600)'}`,
                      padding: '3px 8px',
                    }}
                  >
                    <span style={{ width: 4, height: 4, background: 'currentColor', borderRadius: '50%' }} />
                    {a.status}
                  </span>
                </td>
                <td
                  style={{
                    padding: '12px 10px',
                    borderBottom: '1px solid rgba(248,244,244,0.08)',
                    textAlign: 'right',
                    color: 'var(--color-neutral-400)',
                    verticalAlign: 'top',
                  }}
                >
                  {a.total_runs ?? 0}
                </td>
                <td
                  style={{
                    padding: '12px 0 12px 10px',
                    borderBottom: '1px solid rgba(248,244,244,0.08)',
                    textAlign: 'right',
                    color: 'var(--color-accent-300)',
                    verticalAlign: 'top',
                  }}
                >
                  ${(a.total_cost ?? 0).toFixed(3)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default DelegatesScreen;
