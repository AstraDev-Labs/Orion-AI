import { useAppStore } from '../../lib/store';

/** Discourse — the live transcript of the current conversation, real messages from the store. */
export function DiscourseScreen() {
  const messages = useAppStore((s) => s.messages);

  return (
    <div className="holo-panel holo-boot-in" style={{ position: 'absolute', inset: 0, overflow: 'hidden' }}>
      <div className="holo-corner holo-corner-tl" />
      <div className="holo-corner holo-corner-br" />
      <div style={{ padding: '20px 30px 13px', borderBottom: '1px solid rgba(182,130,53,0.26)' }}>
        <div className="holo-kicker" style={{ marginBottom: 5 }}>
          Transcript · 02
        </div>
        <h2 style={{ fontSize: 26 }}>The current discourse</h2>
      </div>
      <div style={{ height: 'calc(100% - 76px)', overflowY: 'auto', padding: '22px 30px 18px' }}>
        {messages.length === 0 && (
          <p style={{ color: 'var(--color-neutral-600)', fontStyle: 'italic', textAlign: 'center', marginTop: 40 }}>
            No discourse yet — speak at The Core.
          </p>
        )}
        <div style={{ maxWidth: 680, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 22 }}>
          {messages.map((m) => (
            <div key={m.id}>
              <div
                className="holo-kicker"
                style={{
                  marginBottom: 7,
                  textAlign: m.role === 'user' ? 'right' : 'left',
                  color: m.role === 'user' ? 'var(--color-neutral-600)' : 'var(--color-accent)',
                }}
              >
                {m.role === 'user' ? 'You' : 'Orion'} · {new Date(m.timestamp).toLocaleTimeString()}
              </div>
              <p
                style={{
                  margin: m.role === 'user' ? '0 0 0 auto' : 0,
                  maxWidth: m.role === 'user' ? '78%' : '100%',
                  fontSize: 14.5,
                  lineHeight: 1.75,
                  textAlign: m.role === 'user' ? 'right' : 'left',
                  borderRight: m.role === 'user' ? '2px solid var(--color-accent)' : undefined,
                  paddingRight: m.role === 'user' ? 15 : undefined,
                  whiteSpace: 'pre-wrap',
                }}
              >
                {m.content}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default DiscourseScreen;
