import { useCallback, useState } from 'react';
import { useAgentEvents, type AgentEvent } from '../../lib/useAgentEvents';

/** Workflow — a live tail of WORKFLOW_NODE_* / INFERENCE_* / COUNCIL_SEAT_* events off the real bus. */
export function WorkflowScreen() {
  const [events, setEvents] = useState<{ t: string; type: string; detail: string }[]>([]);

  const onEvent = useCallback((event: AgentEvent) => {
    const data = (event.data || {}) as Record<string, unknown>;
    const detail =
      (data.node_id as string) || (data.tool_name as string) || (data.model as string) || (data.seat as string) || '';
    setEvents((prev) =>
      [
        { t: new Date(event.timestamp * 1000).toLocaleTimeString(), type: event.type, detail: String(detail) },
        ...prev,
      ].slice(0, 80),
    );
  }, []);
  useAgentEvents('hud', onEvent, [
    'workflow_node_start',
    'workflow_node_end',
    'inference_start',
    'inference_end',
    'tool_call_start',
    'tool_call_end',
    'council_seat_start',
    'council_seat_end',
  ]);

  return (
    <div className="holo-panel holo-boot-in" style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column' }}>
      <div className="holo-corner holo-corner-tl" />
      <div className="holo-corner holo-corner-br" />
      <div style={{ flexShrink: 0, padding: '20px 30px 13px', borderBottom: '1px solid rgba(182,130,53,0.26)' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
          <div>
            <div className="holo-kicker" style={{ marginBottom: 5 }}>
              Live working · 11
            </div>
            <h2 style={{ fontSize: 26 }}>Workflow</h2>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }} className="holo-kicker">
            <span
              style={{
                width: 5,
                height: 5,
                borderRadius: '50%',
                background: events.length > 0 ? 'var(--color-accent-300)' : 'var(--color-neutral-600)',
                animation: events.length > 0 ? 'holo-breathe 1.3s ease-in-out infinite' : undefined,
              }}
            />
            {events.length > 0 ? 'Live' : 'Idle'}
          </div>
        </div>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '16px 30px 20px' }}>
        {events.length === 0 && (
          <div style={{ color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>
            No workflow, inference, or Council activity yet — this fills in as soon as something runs.
          </div>
        )}
        {events.map((e, i) => (
          <div
            key={i}
            style={{
              display: 'flex',
              gap: 14,
              padding: '9px 0',
              borderBottom: '1px solid rgba(248,244,244,0.08)',
              fontSize: 13,
            }}
          >
            <span style={{ flexShrink: 0, width: 74, color: 'var(--color-neutral-600)', fontFamily: 'ui-monospace, monospace', fontSize: 11 }}>
              {e.t}
            </span>
            <span style={{ flexShrink: 0, fontFamily: 'var(--font-heading)', fontSize: 16, color: 'var(--color-accent-300)' }}>
              {e.type}
            </span>
            <span style={{ color: 'var(--color-neutral-400)' }}>{e.detail}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default WorkflowScreen;
