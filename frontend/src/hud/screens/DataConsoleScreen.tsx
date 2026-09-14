import { useEffect, useState } from 'react';
import { fetchStores, runQuery, type StoreRow } from '../api';

/** Data console — a real, constrained (SELECT-only, allow-listed) query engine over the app's own stores. */
export function DataConsoleScreen() {
  const [stores, setStores] = useState<StoreRow[]>([]);
  const [selectedStore, setSelectedStore] = useState('traces');
  const [sql, setSql] = useState('SELECT * FROM traces ORDER BY started_at DESC LIMIT 20');
  const [result, setResult] = useState<{ columns: string[]; rows: unknown[][]; row_count: number; elapsed_ms: number } | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchStores().then((d) => setStores(d.stores)).catch(() => {});
  }, []);

  const run = async () => {
    setLoading(true);
    setError('');
    try {
      const r = await runQuery(selectedStore, sql);
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'query failed');
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="holo-panel holo-boot-in" style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column' }}>
      <div className="holo-corner holo-corner-tl" />
      <div className="holo-corner holo-corner-br" />
      <div style={{ flexShrink: 0, padding: '20px 30px 13px', borderBottom: '1px solid rgba(182,130,53,0.26)' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 14 }}>
          <div>
            <div className="holo-kicker" style={{ marginBottom: 5 }}>
              Interrogation · 08
            </div>
            <h2 style={{ fontSize: 26 }}>Data console</h2>
          </div>
          {result && (
            <div className="holo-kicker">
              {result.row_count} rows · {result.elapsed_ms} ms
            </div>
          )}
        </div>
        <div
          className="holo-panel"
          style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 13px', borderColor: 'rgba(182,130,53,0.44)' }}
        >
          <select
            value={selectedStore}
            onChange={(e) => setSelectedStore(e.target.value)}
            style={{ background: 'transparent', border: 0, outline: 'none', color: 'var(--color-accent-300)', fontSize: 12 }}
          >
            {stores.map((s) => (
              <option key={s.name} value={s.name} style={{ color: '#000' }}>
                {s.name}
              </option>
            ))}
          </select>
          <input
            value={sql}
            onChange={(e) => setSql(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && run()}
            style={{
              flex: 1,
              minWidth: 0,
              background: 'transparent',
              border: 0,
              outline: 'none',
              fontFamily: 'ui-monospace, monospace',
              fontSize: 12.5,
              color: 'var(--color-neutral-300)',
            }}
          />
          <button className="holo-ghost-btn" style={{ padding: '4px 12px', fontSize: 11.5 }} onClick={run} disabled={loading}>
            Run
          </button>
        </div>
        <p style={{ margin: '6px 0 0', fontSize: 10.5, color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>
          Read-only, SELECT-only, capped at 200 rows. No writes, PRAGMA, or ATTACH are accepted.
        </p>
      </div>

      <div style={{ flex: 1, minHeight: 0, display: 'grid', gridTemplateColumns: '190px minmax(0,1fr)' }}>
        <div style={{ borderRight: '1px solid rgba(182,130,53,0.22)', padding: '16px 16px 16px 30px', overflowY: 'auto' }}>
          <div className="holo-kicker" style={{ marginBottom: 11 }}>
            Stores
          </div>
          {stores.map((s) => (
            <button
              key={s.name}
              onClick={() => setSelectedStore(s.name)}
              style={{
                display: 'block',
                width: '100%',
                textAlign: 'left',
                padding: '8px 0',
                borderBottom: '1px solid rgba(248,244,244,0.07)',
                background: 'transparent',
                border: 0,
                cursor: 'pointer',
              }}
            >
              <div
                style={{
                  fontFamily: 'var(--font-heading)',
                  fontSize: 17,
                  color: selectedStore === s.name ? 'var(--color-accent-300)' : 'var(--color-neutral-200)',
                }}
              >
                {s.name}
              </div>
              <div style={{ fontSize: 10, color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>{s.detail}</div>
            </button>
          ))}
        </div>
        <div style={{ minWidth: 0, overflow: 'auto', padding: '16px 30px 20px 20px' }}>
          {error && <div style={{ color: '#e06b5c', fontSize: 12 }}>{error}</div>}
          {!result && !error && <div style={{ color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>Run a query to see rows.</div>}
          {result && (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
              <thead>
                <tr>
                  {result.columns.map((c) => (
                    <th
                      key={c}
                      style={{
                        textAlign: 'left',
                        fontWeight: 500,
                        fontSize: 9,
                        letterSpacing: '0.18em',
                        textTransform: 'uppercase',
                        color: 'var(--color-neutral-600)',
                        padding: '0 10px 8px 0',
                        borderBottom: '1px solid rgba(182,130,53,0.36)',
                      }}
                    >
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.rows.map((row, i) => (
                  <tr key={i}>
                    {row.map((cell, j) => (
                      <td
                        key={j}
                        style={{
                          padding: '8px 10px 8px 0',
                          borderBottom: '1px solid rgba(248,244,244,0.08)',
                          fontFamily: 'ui-monospace, monospace',
                          fontSize: 11.5,
                          whiteSpace: 'nowrap',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          maxWidth: 260,
                        }}
                      >
                        {String(cell ?? '')}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

export default DataConsoleScreen;
