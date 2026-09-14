import { useEffect, useState } from 'react';
import { fetchAnatomy, type ModelAnatomy } from '../api';

/**
 * Anatomy — real, static facts about the resident model from Ollama's own
 * /api/show. No live per-layer activation chart: Ollama's API has no
 * endpoint for that, so nothing behind such a chart could ever be real.
 */
export function AnatomyScreen() {
  const [info, setInfo] = useState<ModelAnatomy | null>(null);

  useEffect(() => {
    fetchAnatomy().then(setInfo).catch(() => {});
  }, []);

  if (!info) {
    return (
      <div className="holo-panel holo-boot-in" style={{ position: 'absolute', inset: 0, padding: '20px 30px', color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>
        Reading…
      </div>
    );
  }

  if (!info.available) {
    return (
      <div className="holo-panel holo-boot-in" style={{ position: 'absolute', inset: 0, padding: '20px 30px' }}>
        <h2 style={{ fontSize: 26, marginBottom: 10 }}>Anatomy of the lattice</h2>
        <p style={{ color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>{info.reason}</p>
      </div>
    );
  }

  const figures = [
    { label: 'Parameters', value: info.parameter_size || '—' },
    { label: 'Quantization', value: info.quantization_level || '—' },
    { label: 'Layers', value: info.layer_count != null ? String(info.layer_count) : '—' },
    { label: 'Context', value: info.context_length ? info.context_length.toLocaleString() : '—' },
    { label: 'Embedding', value: info.embedding_length != null ? String(info.embedding_length) : '—' },
  ];

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
            Neural architecture · 10
          </div>
          <h2 style={{ fontSize: 26 }}>Anatomy of the lattice</h2>
        </div>
        <div className="holo-kicker">{info.model}</div>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
          border: '1px solid rgba(182,130,53,0.28)',
          marginBottom: 22,
        }}
      >
        {figures.map((f) => (
          <div key={f.label} style={{ padding: '15px 16px 14px', borderRight: '1px solid rgba(182,130,53,0.2)' }}>
            <div className="holo-kicker" style={{ marginBottom: 8 }}>
              {f.label}
            </div>
            <div style={{ fontFamily: 'var(--font-heading)', fontWeight: 300, fontSize: 30, color: 'var(--color-accent-300)' }}>
              {f.value}
            </div>
          </div>
        ))}
      </div>

      <h3 style={{ fontSize: 17, fontWeight: 400, marginBottom: 12 }}>Capabilities</h3>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 22 }}>
        {(info.capabilities || []).map((c) => (
          <span
            key={c}
            style={{
              fontSize: 10.5,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              color: 'var(--color-accent-300)',
              border: '1px solid rgba(182,130,53,0.4)',
              padding: '4px 10px',
            }}
          >
            {c}
          </span>
        ))}
        {(info.capabilities || []).length === 0 && (
          <span style={{ color: 'var(--color-neutral-600)', fontStyle: 'italic', fontSize: 12 }}>none reported</span>
        )}
      </div>

      <h3 style={{ fontSize: 17, fontWeight: 400, marginBottom: 12 }}>Adapters</h3>
      {(info.adapters || []).length === 0 ? (
        <p style={{ color: 'var(--color-neutral-600)', fontStyle: 'italic', fontSize: 12.5 }}>None configured.</p>
      ) : (
        (info.adapters || []).map((a) => (
          <div key={a} style={{ padding: '8px 0', borderBottom: '1px solid rgba(248,244,244,0.08)', fontSize: 13 }}>
            {a}
          </div>
        ))
      )}

      <p style={{ marginTop: 24, fontSize: 11.5, color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>
        These are real architecture facts from Ollama. Live per-layer activation is not shown — Ollama's API has no
        endpoint that exposes it.
      </p>
    </div>
  );
}

export default AnatomyScreen;
