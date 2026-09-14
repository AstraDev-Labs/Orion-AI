import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  searchMemory,
  fetchMemoryGraph,
  fetchRelationship,
  type MemoryResult,
  type MemoryGraphNode,
  type MemoryGraphEdge,
  type RelationshipSummary,
} from '../api';

type PositionedNode = MemoryGraphNode & { x: number; y: number };

/** Lay out nodes on concentric rings by recency -- newest closest to
 * center, matching the "core lattice" visual language used elsewhere
 * in the shell -- radius and angle are deterministic from real data
 * (index + creation time), never randomized or faked. */
function layoutRadial(nodes: MemoryGraphNode[], width: number, height: number): PositionedNode[] {
  const cx = width / 2;
  const cy = height / 2;
  const sorted = [...nodes].sort((a, b) => b.created_at - a.created_at);
  const perRing = 8;
  return sorted.map((n, i) => {
    const ring = Math.floor(i / perRing);
    const idxInRing = i % perRing;
    const ringCount = Math.min(perRing, sorted.length - ring * perRing);
    const angle = (idxInRing / Math.max(1, ringCount)) * Math.PI * 2 + ring * 0.4;
    const radius = 46 + ring * 68;
    return { ...n, x: cx + Math.cos(angle) * radius, y: cy + Math.sin(angle) * radius };
  });
}

type ViewBox = { x: number; y: number; w: number; h: number };

const MIN_ZOOM_W = 60; // most zoomed in: 60 layout units across
const MAX_ZOOM_W = 8000; // most zoomed out

/** The smallest view (at the graph's aspect ratio) that shows every node. */
function fitView(nodes: PositionedNode[], width: number, height: number): ViewBox {
  if (nodes.length === 0) return { x: 0, y: 0, w: width, h: height };
  const xs = nodes.map((n) => n.x);
  const ys = nodes.map((n) => n.y);
  const pad = 40;
  const minX = Math.min(...xs) - pad;
  const maxX = Math.max(...xs) + pad;
  const minY = Math.min(...ys) - pad;
  const maxY = Math.max(...ys) + pad;
  const aspect = width / height;
  let w = Math.max(maxX - minX, 120);
  let h = Math.max(maxY - minY, 120 / aspect);
  if (w / h > aspect) h = w / aspect;
  else w = h * aspect;
  return { x: (minX + maxX) / 2 - w / 2, y: (minY + maxY) / 2 - h / 2, w, h };
}

/** Recollection — the memory graph Orion has actually captured (real,
 * persistent, connected by real embedding similarity -- see
 * memory_capture.py), plus the existing free-text recall search. */
export function RecollectionScreen() {
  const [nodes, setNodes] = useState<MemoryGraphNode[]>([]);
  const [edges, setEdges] = useState<MemoryGraphEdge[]>([]);
  const [graphNote, setGraphNote] = useState('');
  const [hovered, setHovered] = useState<string | null>(null);
  const [relationship, setRelationship] = useState<RelationshipSummary | null>(null);

  const [query, setQuery] = useState('');
  const [results, setResults] = useState<MemoryResult[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadGraph = () =>
    fetchMemoryGraph()
      .then((d) => {
        setNodes(d.nodes);
        setEdges(d.edges);
        setGraphNote(d.note || '');
      })
      .catch(() => {});

  useEffect(() => {
    loadGraph();
    const id = setInterval(loadGraph, 15000);
    fetchRelationship().then(setRelationship).catch(() => {});
    const id2 = setInterval(() => fetchRelationship().then(setRelationship).catch(() => {}), 30000);
    return () => {
      clearInterval(id);
      clearInterval(id2);
    };
  }, []);

  const run = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError('');
    try {
      const r = await searchMemory(query.trim());
      setResults(r.results);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'search failed');
    } finally {
      setLoading(false);
    }
  };

  const W = 560;
  const H = 420;
  const positioned = useMemo(() => layoutRadial(nodes, W, H), [nodes]);
  const byId = useMemo(() => new Map(positioned.map((n) => [n.id, n])), [positioned]);

  // Pan & zoom. The rings grow outward with every memory, so a fixed view
  // cut the outer ones off; the view starts fitted to all nodes and can be
  // zoomed (wheel / buttons) and dragged. The 15 s refresh never resets a
  // view the user has moved.
  const [view, setView] = useState<ViewBox>({ x: 0, y: 0, w: W, h: H });
  const userMovedRef = useRef(false);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const dragRef = useRef<{ px: number; py: number; view: ViewBox } | null>(null);

  const fitAll = useCallback(() => {
    userMovedRef.current = false;
    setView(fitView(positioned, W, H));
  }, [positioned]);

  useEffect(() => {
    if (!userMovedRef.current) setView(fitView(positioned, W, H));
  }, [positioned]);

  const zoomAt = useCallback((factor: number, clientX?: number, clientY?: number) => {
    userMovedRef.current = true;
    setView((v) => {
      const w = Math.min(MAX_ZOOM_W, Math.max(MIN_ZOOM_W, v.w * factor));
      const scale = w / v.w;
      const h = v.h * scale;
      const rect = svgRef.current?.getBoundingClientRect();
      // Zoom toward the cursor when there is one, else the center.
      const fx = rect && clientX !== undefined ? (clientX - rect.left) / rect.width : 0.5;
      const fy = rect && clientY !== undefined ? (clientY - rect.top) / rect.height : 0.5;
      return { x: v.x + (v.w - w) * fx, y: v.y + (v.h - h) * fy, w, h };
    });
  }, []);

  // Native, non-passive wheel listener: React's onWheel is passive, so it
  // cannot stop the page from scrolling while zooming the graph.
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      zoomAt(e.deltaY > 0 ? 1.15 : 1 / 1.15, e.clientX, e.clientY);
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [zoomAt, nodes.length]);

  const onPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    if (e.button !== 0) return;
    dragRef.current = { px: e.clientX, py: e.clientY, view };
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const drag = dragRef.current;
    const rect = svgRef.current?.getBoundingClientRect();
    if (!drag || !rect) return;
    const dx = ((e.clientX - drag.px) / rect.width) * drag.view.w;
    const dy = ((e.clientY - drag.py) / rect.height) * drag.view.h;
    if (Math.abs(dx) + Math.abs(dy) > 0.5) userMovedRef.current = true;
    setView({ ...drag.view, x: drag.view.x - dx, y: drag.view.y - dy });
  };
  const endDrag = () => {
    dragRef.current = null;
  };

  // Keep dots, lines and labels the same size on screen at any zoom.
  const k = view.w / W;

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
            Index · 04
          </div>
          <h2 style={{ fontSize: 26 }}>Recollection</h2>
        </div>
        <div className="holo-kicker">
          {nodes.length} {nodes.length === 1 ? 'memory' : 'memories'} · {edges.length} {edges.length === 1 ? 'connection' : 'connections'}
        </div>
      </div>

      {relationship && relationship.total_memories > 0 && (
        <p
          style={{
            margin: '0 0 16px',
            fontSize: 12.5,
            lineHeight: 1.6,
            color: 'var(--color-neutral-400)',
            fontStyle: 'italic',
          }}
        >
          {relationship.text}
        </p>
      )}

      {/* The graph: every captured memory as a node, connected by real
          embedding-similarity edges. An empty graph is shown honestly,
          not padded with placeholder nodes. */}
      <div
        className="holo-panel"
        style={{
          position: 'relative',
          width: '100%',
          height: H,
          marginBottom: 22,
          borderColor: 'rgba(182,130,53,0.3)',
          overflow: 'hidden',
        }}
      >
        {nodes.length === 0 ? (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--color-neutral-600)',
              fontStyle: 'italic',
              fontSize: 12.5,
              textAlign: 'center',
              padding: '0 40px',
            }}
          >
            {graphNote || 'Nothing captured yet — this fills in as you talk to Orion.'}
          </div>
        ) : (
          <>
          <svg
            ref={svgRef}
            viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
            width="100%"
            height="100%"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
            onDoubleClick={fitAll}
            style={{ cursor: dragRef.current ? 'grabbing' : 'grab', touchAction: 'none', userSelect: 'none' }}
          >
            {edges.map((e, i) => {
              const a = byId.get(e.source);
              const b = byId.get(e.target);
              if (!a || !b) return null;
              const dim = hovered && hovered !== e.source && hovered !== e.target;
              return (
                <line
                  key={i}
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  stroke="var(--color-accent-300)"
                  strokeWidth={(0.5 + e.weight * 1.5) * k}
                  opacity={dim ? 0.05 : 0.15 + e.weight * 0.35}
                />
              );
            })}
            {positioned.map((n) => {
              const isHovered = hovered === n.id;
              const connected = edges.some((e) => e.source === n.id || e.target === n.id);
              return (
                <g
                  key={n.id}
                  transform={`translate(${n.x},${n.y}) scale(${k})`}
                  style={{ cursor: 'default' }}
                  onMouseEnter={() => setHovered(n.id)}
                  onMouseLeave={() => setHovered((h) => (h === n.id ? null : h))}
                >
                  <circle
                    r={isHovered ? 7 : 4.5}
                    fill={connected ? 'var(--color-accent-300)' : 'var(--color-neutral-600)'}
                    opacity={hovered && !isHovered ? 0.35 : 0.9}
                    style={{ transition: 'r 0.15s' }}
                  />
                  {isHovered && (
                    <foreignObject x={-100} y={10} width={200} height={70} style={{ overflow: 'visible', pointerEvents: 'none' }}>
                      <div
                        style={{
                          background: 'rgba(16,14,11,0.94)',
                          border: '1px solid rgba(182,130,53,0.5)',
                          padding: '6px 9px',
                          fontSize: 10.5,
                          lineHeight: 1.5,
                          color: 'var(--color-neutral-200)',
                          textAlign: 'center',
                        }}
                      >
                        {n.label}
                      </div>
                    </foreignObject>
                  )}
                </g>
              );
            })}
          </svg>
          <div style={{ position: 'absolute', top: 10, right: 10, display: 'flex', gap: 6 }}>
            <button className="holo-ghost-btn" title="Zoom in" aria-label="Zoom in" onClick={() => zoomAt(1 / 1.3)} style={{ padding: '2px 10px' }}>
              +
            </button>
            <button className="holo-ghost-btn" title="Zoom out" aria-label="Zoom out" onClick={() => zoomAt(1.3)} style={{ padding: '2px 10px' }}>
              −
            </button>
            <button className="holo-ghost-btn" title="Show every memory" onClick={fitAll} style={{ padding: '2px 10px', fontSize: 10 }}>
              Fit
            </button>
          </div>
          <div
            style={{
              position: 'absolute',
              left: 12,
              bottom: 8,
              fontSize: 10,
              color: 'var(--color-neutral-600)',
              fontStyle: 'italic',
              pointerEvents: 'none',
            }}
          >
            Scroll to zoom · drag to move · double-click to fit
          </div>
          </>
        )}
      </div>

      <div style={{ display: 'flex', gap: 10, marginBottom: 20 }}>
        <div
          className="holo-panel"
          style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 10, padding: '11px 14px', borderColor: 'rgba(182,130,53,0.44)' }}
        >
          <span style={{ color: 'var(--color-accent)' }}>⌕</span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && run()}
            placeholder="Ask what Orion has kept…"
            style={{ flex: 1, background: 'transparent', border: 0, outline: 'none', fontSize: 14, color: 'var(--color-neutral-100)' }}
          />
        </div>
        <button className="holo-ghost-btn" onClick={run} disabled={loading || !query.trim()}>
          {loading ? 'Recalling…' : 'Recall'}
        </button>
      </div>

      {error && <div style={{ color: '#e06b5c', fontSize: 12, marginBottom: 12 }}>{error}</div>}

      {results !== null && results.length === 0 && !error && (
        <div style={{ color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>Nothing found for that query.</div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: 13 }}>
        {(results || []).map((m, i) => (
          <div key={i} style={{ border: '1px solid rgba(182,130,53,0.28)', padding: '14px 15px' }}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                fontSize: 9,
                letterSpacing: '0.16em',
                textTransform: 'uppercase',
                color: 'var(--color-neutral-600)',
                marginBottom: 8,
              }}
            >
              <span>{(m.metadata?.kind as string) || 'memory'}</span>
              <span style={{ color: 'var(--color-accent-300)' }}>{m.score.toFixed(2)}</span>
            </div>
            <p style={{ margin: 0, fontSize: 13.5, lineHeight: 1.7 }}>{m.content}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export default RecollectionScreen;
