import { useCallback, useEffect, useState } from 'react';
import { fetchTraces, type TraceRow } from '../api';
import { useAgentEvents, type AgentEvent } from '../../lib/useAgentEvents';

/** The Chronicle — historical traces from /v1/traces plus a live tail off the event bus. */
export function ChronicleScreen() {
  const [historical, setHistorical] = useState<TraceRow[]>([]);
  const [note, setNote] = useState('');
  const [live, setLive] = useState<{ t: string; level: string; source: string; message: string }[]>([]);

  useEffect(() => {
    fetchTraces(60)
      .then((d) => {
        setHistorical(d.traces);
        if (d.note) setNote(d.note);
      })
      .catch(() => {});
  }, []);

  const onEvent = useCallback((event: AgentEvent) => {
    const data = (event.data || {}) as Record<string, unknown>;
    const message =
      (data.tool_name as string) || (data.preview as string) || (data.model as string) || (data.seat as string) || '';
    setLive((prev) =>
      [
        {
          t: new Date(event.timestamp * 1000).toLocaleTimeString(),
          level: event.type.includes('error') ? 'error' : 'info',
          source: event.type,
          message: String(message).slice(0, 80),
        },
        ...prev,
      ].slice(0, 60),
    );
  }, []);
  useAgentEvents('hud', onEvent);

  const rows = [
    ...live.map((r) => ({ ...r, key: `live-${r.t}-${r.source}` })),
    ...historical.map((t) => ({
      t: new Date(t.started_at * 1000).toLocaleTimeString(),
      level: t.outcome === 'error' ? 'error' : 'ok',
      source: t.agent || t.model || 'trace',
      message: t.query,
      key: t.trace_id,
    })),
  ];

  return (
    <div className="holo-panel holo-boot-in" style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column' }}>
      <div className="holo-corner holo-corner-tl" />
      <div className="holo-corner holo-corner-br" />
      <div style={{ flexShrink: 0, padding: '20px 30px 13px', borderBottom: '1px solid rgba(182,130,53,0.26)' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
          <div>
            <div className="holo-kicker" style={{ marginBottom: 5 }}>
              Record · 09
            </div>
            <h2 style={{ fontSize: 26 }}>The Chronicle</h2>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }} className="holo-kicker">
            <span
              style={{
                width: 5,
                height: 5,
                borderRadius: '50%',
                background: 'var(--color-accent-300)',
                animation: 'holo-breathe 1.3s ease-in-out infinite',
              }}
            />
            Streaming
          </div>
        </div>
        {note && <p style={{ fontSize: 11, color: 'var(--color-neutral-600)', fontStyle: 'italic', marginTop: 8 }}>{note}</p>}
      </div>
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '6px 30px 20px' }}>
        {rows.length === 0 && (
          <div style={{ color: 'var(--color-neutral-600)', fontStyle: 'italic', marginTop: 20 }}>Nothing recorded yet.</div>
        )}
        {rows.map((r) => (
          <div
            key={r.key}
            style={{ display: 'flex', gap: 14, alignItems: 'baseline', padding: '8px 0', borderBottom: '1px solid rgba(248,244,244,0.07)', fontSize: 12.5 }}
          >
            <span style={{ flexShrink: 0, width: 74, color: 'var(--color-neutral-600)', fontFamily: 'ui-monospace, monospace', fontSize: 11 }}>
              {r.t}
            </span>
            <span
              style={{
                flexShrink: 0,
                width: 50,
                fontSize: 9,
                letterSpacing: '0.14em',
                textTransform: 'uppercase',
                color: r.level === 'error' ? '#e06b5c' : 'var(--color-accent-300)',
              }}
            >
              {r.level}
            </span>
            <span style={{ flexShrink: 0, width: 110, fontStyle: 'italic', color: 'var(--color-accent)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {r.source}
            </span>
            <span style={{ flex: 1, minWidth: 0, color: 'var(--color-neutral-300)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {r.message}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default ChronicleScreen;
