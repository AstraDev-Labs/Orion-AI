import { useEffect, useState } from 'react';
import { fetchSavingsSummary, type SavingsSummary } from '../api';

/** Reckoning — real numbers from the savings/telemetry engine, /v1/savings. */
export function ReckoningScreen() {
  const [summary, setSummary] = useState<SavingsSummary | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    fetchSavingsSummary()
      .then(setSummary)
      .catch((e) => setError(e.message));
  }, []);

  const totalAvoided = summary?.per_provider.reduce((a, p) => a + p.total_cost, 0) ?? 0;
  const maxCost = Math.max(1e-9, ...(summary?.per_provider.map((p) => p.total_cost) || [0]));

  const figures = summary
    ? [
        { label: 'Calls', value: String(summary.total_calls), sub: `${summary.total_tokens.toLocaleString()} tokens` },
        { label: 'Local cost', value: `$${summary.local_cost.toFixed(3)}`, sub: 'always $0 for local inference' },
        { label: 'Avoided', value: `$${totalAvoided.toFixed(3)}`, sub: 'vs. cloud, this session' },
        { label: 'Session', value: `${summary.session_duration_hours.toFixed(1)}h`, sub: 'elapsed' },
      ]
    : [];

  return (
    <div className="holo-panel holo-boot-in" style={{ position: 'absolute', inset: 0, overflowY: 'auto', padding: '20px 30px 24px' }}>
      <div className="holo-corner holo-corner-tl" />
      <div className="holo-corner holo-corner-br" />
      <div style={{ paddingBottom: 13, borderBottom: '1px solid rgba(182,130,53,0.26)', marginBottom: 20 }}>
        <div className="holo-kicker" style={{ marginBottom: 5 }}>
          Accounts · 05
        </div>
        <h2 style={{ fontSize: 26 }}>The reckoning</h2>
      </div>

      {error && <div style={{ color: '#e06b5c', fontSize: 12 }}>{error}</div>}
      {!summary && !error && <div style={{ color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>Reading…</div>}

      {summary && (
        <>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
              border: '1px solid rgba(182,130,53,0.28)',
              marginBottom: 22,
            }}
          >
            {figures.map((f) => (
              <div key={f.label} style={{ padding: '16px 16px 14px', borderRight: '1px solid rgba(182,130,53,0.2)' }}>
                <div className="holo-kicker" style={{ marginBottom: 9 }}>
                  {f.label}
                </div>
                <div style={{ fontFamily: 'var(--font-heading)', fontWeight: 300, fontSize: 36, color: 'var(--color-accent-300)' }}>
                  {f.value}
                </div>
                <div style={{ fontSize: 10.5, color: 'var(--color-neutral-600)', fontStyle: 'italic', marginTop: 6 }}>{f.sub}</div>
              </div>
            ))}
          </div>

          <h3 style={{ fontSize: 17, fontWeight: 400, marginBottom: 12 }}>Avoided, by provider</h3>
          {summary.per_provider.length === 0 && (
            <div style={{ color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>No provider comparisons yet.</div>
          )}
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13.5 }}>
            <tbody>
              {summary.per_provider.map((p) => (
                <tr key={p.provider}>
                  <td style={{ padding: '10px 0', borderBottom: '1px solid rgba(248,244,244,0.08)', color: 'var(--color-neutral-400)' }}>
                    {p.label}
                  </td>
                  <td style={{ padding: '10px 12px', borderBottom: '1px solid rgba(248,244,244,0.08)', width: '50%' }}>
                    <div className="holo-bar-track">
                      <div className="holo-bar-fill" style={{ width: `${(p.total_cost / maxCost) * 100}%` }} />
                    </div>
                  </td>
                  <td
                    style={{
                      padding: '10px 0',
                      borderBottom: '1px solid rgba(248,244,244,0.08)',
                      textAlign: 'right',
                      width: 88,
                      color: 'var(--color-accent-300)',
                    }}
                  >
                    ${p.total_cost.toFixed(3)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

export default ReckoningScreen;
