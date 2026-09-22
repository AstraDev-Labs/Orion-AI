import { useCallback, useEffect, useMemo, useState } from 'react';
import './hud.css';
import { getBase } from '../lib/api';
import {
  fetchVitals,
  fetchChannelStatus,
  fetchTools,
  toggleTool as toggleToolApi,
  fetchAffect,
  fetchConnections,
  toolLabel,
  type VitalRow,
  type ToolRow,
  type AffectState,
} from './api';
import { useAgentEvents, type AgentEvent } from '../lib/useAgentEvents';
import { HolotableScene, type HolotableActivity } from './holo/HolotableScene';
import { AuditoryPanel } from './panels/AuditoryPanel';
import { AvoidedPanel } from './panels/AvoidedPanel';
import { CoreScreen } from './screens/CoreScreen';
import { recordUntilSilence, SPEECH_AUDIO_CONSTRAINTS } from '../lib/voiceCapture';
import { transcribeAudio } from '../lib/api';
import { WorkflowScreen } from './screens/WorkflowScreen';
import { DiscourseScreen } from './screens/DiscourseScreen';
import { DelegatesScreen } from './screens/DelegatesScreen';
import { RecollectionScreen } from './screens/RecollectionScreen';
import { ReckoningScreen } from './screens/ReckoningScreen';
import { GovernanceScreen } from './screens/GovernanceScreen';
import { CouncilScreen } from './screens/CouncilScreen';
import { DataConsoleScreen } from './screens/DataConsoleScreen';
import { ChronicleScreen } from './screens/ChronicleScreen';
import { AnatomyScreen } from './screens/AnatomyScreen';
import { ConnectionsScreen } from './screens/ConnectionsScreen';

const SCREENS = [
  { key: 'core', num: '01', label: 'The Core', digit: '1' },
  { key: 'discourse', num: '02', label: 'Discourse', digit: '2' },
  { key: 'delegates', num: '03', label: 'Delegates', digit: '3' },
  { key: 'recollection', num: '04', label: 'Recollection', digit: '4' },
  { key: 'reckoning', num: '05', label: 'Reckoning', digit: '5' },
  { key: 'governance', num: '06', label: 'Governance', digit: '6' },
  { key: 'council', num: '07', label: 'The Council', digit: '7' },
  { key: 'data', num: '08', label: 'Data console', digit: '8' },
  { key: 'chronicle', num: '09', label: 'The Chronicle', digit: '9' },
  { key: 'anatomy', num: '10', label: 'Anatomy', digit: '0' },
  { key: 'workflow', num: '11', label: 'Workflow', digit: 'w' },
  { key: 'connections', num: '12', label: 'Connections', digit: 'c' },
] as const;

type ScreenKey = (typeof SCREENS)[number]['key'];

function LedgerPanel() {
  const [rows, setRows] = useState<{ t: string; type: string; detail: string }[]>([]);
  const onEvent = useCallback((event: AgentEvent) => {
    const data = (event.data || {}) as Record<string, unknown>;
    const detail =
      (data.tool_name as string) || (data.preview as string) || (data.sender as string) || (data.seat as string) || '';
    setRows((prev) =>
      [
        { t: new Date(event.timestamp * 1000).toLocaleTimeString(), type: event.type, detail: String(detail).slice(0, 60) },
        ...prev,
      ].slice(0, 40),
    );
  }, []);
  useAgentEvents('hud', onEvent);

  return (
    <div className="holo-panel" style={{ padding: '13px 14px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }} className="holo-kicker">
        <span>Ledger</span>
        <span style={{ color: 'var(--color-accent-300)' }}>{rows.length}</span>
      </div>
      <div style={{ maxHeight: 168, overflowY: 'auto' }}>
        {rows.length === 0 && (
          <div style={{ fontSize: 11, color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>Waiting for activity…</div>
        )}
        {rows.map((r, i) => (
          <div
            key={i}
            style={{
              display: 'flex',
              gap: 9,
              padding: '5px 0',
              borderBottom: '1px solid rgba(248,244,244,0.07)',
              fontSize: 10.5,
              alignItems: 'baseline',
            }}
          >
            <span style={{ color: 'var(--color-neutral-600)', flexShrink: 0 }}>{r.t}</span>
            <span style={{ color: 'var(--color-accent-300)', flexShrink: 0, fontStyle: 'italic' }}>{r.type}</span>
            <span
              style={{
                color: 'var(--color-neutral-400)',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {r.detail}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function VitalsPanel() {
  const [vitals, setVitals] = useState<VitalRow[]>([]);
  useEffect(() => {
    let alive = true;
    const load = () => fetchVitals().then((d) => alive && setVitals(d.vitals)).catch(() => {});
    load();
    const id = setInterval(load, 8000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);
  return (
    <div className="holo-panel" style={{ padding: '14px 15px' }}>
      <div className="holo-kicker" style={{ marginBottom: 11 }}>
        Vitals
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 11 }}>
        {vitals.length === 0 && (
          <div style={{ fontSize: 11, color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>Reading…</div>
        )}
        {vitals.map((v) => (
          <div key={v.label}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                fontSize: 10,
                letterSpacing: '0.14em',
                textTransform: 'uppercase',
                color: 'var(--color-neutral-400)',
                marginBottom: 4,
              }}
            >
              <span>{v.label}</span>
              <span style={{ color: 'var(--color-accent-300)', fontSize: 12 }}>{v.value}</span>
            </div>
            <div className="holo-bar-track">
              <div className="holo-bar-fill" style={{ width: v.pct }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ConduitsPanel({ onOpen }: { onOpen: () => void }) {
  const [status, setStatus] = useState('');
  const [linked, setLinked] = useState<{ connected: number; total: number } | null>(null);
  useEffect(() => {
    fetchConnections()
      .then((d) =>
        setLinked({ connected: d.connections.filter((c) => c.status === 'connected').length, total: d.connections.length }),
      )
      .catch(() => {});
  }, []);
  useEffect(() => {
    let alive = true;
    const load = () => fetchChannelStatus().then((d) => alive && setStatus(d.status)).catch(() => {});
    load();
    const id = setInterval(load, 10000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);
  const color = status === 'connected' ? 'var(--color-accent-300)' : 'var(--color-neutral-600)';
  return (
    <div className="holo-panel" style={{ padding: '14px 15px' }}>
      <div className="holo-kicker" style={{ marginBottom: 11 }}>
        Conduits
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', fontSize: 12.5 }}>
        <span>WhatsApp</span>
        <span style={{ fontSize: 9, letterSpacing: '0.14em', textTransform: 'uppercase', color }}>
          {status || 'unknown'}
        </span>
      </div>
      <button
        onClick={onOpen}
        className="holo-ghost-btn"
        style={{ width: '100%', marginTop: 8, fontSize: 10.5, display: 'flex', justifyContent: 'space-between' }}
      >
        <span>Connections</span>
        <span>{linked ? `${linked.connected} / ${linked.total}` : '→'}</span>
      </button>
    </div>
  );
}

function ToolsPanel() {
  const [tools, setTools] = useState<ToolRow[]>([]);
  useEffect(() => {
    fetchTools().then((d) => setTools(d.tools)).catch(() => {});
  }, []);
  const enabledCount = tools.filter((t) => t.enabled).length;
  const toggle = async (tool: ToolRow) => {
    setTools((prev) => prev.map((t) => (t.name === tool.name ? { ...t, enabled: !t.enabled } : t)));
    try {
      await toggleToolApi(tool.name, !tool.enabled);
    } catch {
      setTools((prev) => prev.map((t) => (t.name === tool.name ? { ...t, enabled: tool.enabled } : t)));
    }
  };
  return (
    <div className="holo-panel" style={{ padding: '13px 14px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }} className="holo-kicker">
        <span>Tools</span>
        <span style={{ color: 'var(--color-accent-300)' }}>
          {enabledCount} / {tools.length}
        </span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 5, maxHeight: 220, overflowY: 'auto' }}>
        {tools.map((t) => (
          <button
            key={t.name}
            title={t.description}
            onClick={() => toggle(t)}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 6,
              padding: '5px 7px',
              border: `1px solid ${t.enabled ? 'rgba(182,130,53,0.6)' : 'rgba(182,130,53,0.2)'}`,
              background: 'transparent',
              fontSize: 10.5,
              color: t.enabled ? 'var(--color-accent-300)' : 'var(--color-neutral-600)',
              cursor: 'pointer',
              textAlign: 'left',
            }}
          >
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{toolLabel(t.name)}</span>
            <span
              style={{
                flexShrink: 0,
                width: 4,
                height: 4,
                borderRadius: '50%',
                background: t.enabled ? 'var(--color-accent-300)' : 'var(--color-neutral-600)',
              }}
            />
          </button>
        ))}
      </div>
    </div>
  );
}

export function HolotableShell() {
  const [screen, setScreen] = useState<ScreenKey>('core');
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [micOn, setMicOn] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [voiceInput, setVoiceInput] = useState<{ id: number; text: string } | null>(null);
  const [listenTick, setListenTick] = useState(0);
  const [voiceStatus, setVoiceStatus] = useState<'idle' | 'listening' | 'transcribing' | 'error'>('idle');
  const [firingRate, setFiringRate] = useState(0);
  const [backendUp, setBackendUp] = useState(true);
  const [affect, setAffect] = useState<AffectState | null>(null);

  useEffect(() => {
    let alive = true;
    const ping = async () => {
      try {
        const res = await fetch(`${getBase()}/health`);
        if (alive) setBackendUp(res.ok);
      } catch {
        if (alive) setBackendUp(false);
      }
    };
    ping();
    const id = setInterval(ping, 8000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    let alive = true;
    const load = () => fetchAffect().then((d) => alive && setAffect(d)).catch(() => {});
    load();
    // Session-wide signal (momentum) moves slowly; no need to poll fast.
    const id = setInterval(load, 20000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  // Real, not decorative: listening reflects the actual mic toggle, thinking
  // reflects an actual in-flight chat stream, and idle is the honest default
  // for everything else -- no state here is faked to look busier than it is.
  const activity: HolotableActivity = speaking
    ? 'speaking'
    : streaming
      ? 'thinking'
      : micOn
        ? 'listening'
        : 'idle';

  // Hands-free voice loop. While the mic is on and Orion is neither thinking
  // nor speaking: record, stop ~1.2s after the user goes quiet (see
  // lib/voiceCapture.ts), transcribe, and hand the text to the Core. Listening
  // pauses while a reply is generated and spoken, so Orion never transcribes
  // its own voice, then re-arms. listenTick re-arms after an empty capture.
  useEffect(() => {
    if (!micOn || streaming || speaking) {
      if (!micOn) setVoiceStatus('idle');
      return;
    }
    let disposed = false;
    let stream: MediaStream | null = null;
    let handle: { cancel: () => void } | null = null;

    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: SPEECH_AUDIO_CONSTRAINTS });
        if (disposed) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        setVoiceStatus('listening');
        handle = await recordUntilSilence(stream, async (blob) => {
          stream?.getTracks().forEach((t) => t.stop());
          if (disposed) return;
          if (blob.size === 0) {
            setListenTick((n) => n + 1); // nothing was said; listen again
            return;
          }
          setVoiceStatus('transcribing');
          try {
            const { text } = await transcribeAudio(blob);
            if (disposed) return;
            const clean = (text || '').trim();
            if (clean) setVoiceInput({ id: Date.now(), text: clean });
            else setListenTick((n) => n + 1);
          } catch {
            if (!disposed) {
              setVoiceStatus('error');
              setTimeout(() => setListenTick((n) => n + 1), 1500);
            }
          }
        });
      } catch {
        if (!disposed) setVoiceStatus('error');
      }
    })();

    return () => {
      disposed = true;
      handle?.cancel();
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, [micOn, streaming, speaking, listenTick]);

  // Dev-only: drive the full voice path (Core send → spoken reply → TTS) from
  // the console or an automated browser, without a microphone.
  useEffect(() => {
    if (!import.meta.env.DEV) return;
    const w = window as unknown as { __orionVoice?: (text: string) => void };
    w.__orionVoice = (text: string) => setVoiceInput({ id: Date.now(), text });
    return () => {
      delete w.__orionVoice;
    };
  }, []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setPaletteOpen((v) => !v);
        return;
      }
      if (paletteOpen) return;
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA') return;
      const found = SCREENS.find((s) => s.digit.toLowerCase() === e.key.toLowerCase());
      if (found) setScreen(found.key);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [paletteOpen]);

  // Keep The Core mounted while the user examines another section. A chat
  // stream owns local state for its partial text, timers and speech queue;
  // unmounting it mid-reply made navigation look like the answer had been cut
  // off. `hidden` removes it from view without destroying that in-flight work.
  const detailScreen = useMemo(() => {
    switch (screen) {
      case 'discourse':
        return <DiscourseScreen />;
      case 'delegates':
        return <DelegatesScreen />;
      case 'recollection':
        return <RecollectionScreen />;
      case 'reckoning':
        return <ReckoningScreen />;
      case 'governance':
        return <GovernanceScreen />;
      case 'council':
        return <CouncilScreen />;
      case 'data':
        return <DataConsoleScreen />;
      case 'chronicle':
        return <ChronicleScreen />;
      case 'anatomy':
        return <AnatomyScreen />;
      case 'workflow':
        return <WorkflowScreen />;
      case 'connections':
        return <ConnectionsScreen />;
      default:
        return null;
    }
  }, [screen]);

  return (
    <div className="holo-root" style={{ display: 'flex', flexDirection: 'column', padding: 15, gap: 13, boxSizing: 'border-box' }}>
      <div style={{ position: 'absolute', inset: 0, zIndex: 0 }}>
        <HolotableScene
          activity={activity}
          link={backendUp ? 'live' : 'offline'}
          affect={affect?.label ?? 'steady'}
        />
      </div>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          pointerEvents: 'none',
          zIndex: 1,
          background: 'radial-gradient(760px 620px at 50% 50%, transparent 0%, rgba(16,14,11,0.28) 58%, rgba(16,14,11,0.82) 100%)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          height: 140,
          pointerEvents: 'none',
          zIndex: 1,
          background: 'linear-gradient(180deg, transparent, rgba(250,203,141,0.04), transparent)',
          animation: 'holo-scanline 9s linear infinite',
        }}
      />

      <header
        className="holo-panel holo-boot-in"
        style={{ flexShrink: 0, display: 'flex', alignItems: 'stretch', overflow: 'hidden', zIndex: 2 }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'baseline',
            gap: 12,
            padding: '9px 18px',
            borderRight: '1px solid rgba(182,130,53,0.34)',
          }}
        >
          <span style={{ fontFamily: 'var(--font-heading)', fontSize: 23, letterSpacing: '0.38em' }}>ORION</span>
          <span style={{ fontSize: 9.5, letterSpacing: '0.3em', textTransform: 'uppercase', color: 'var(--color-accent)' }}>
            Mk IV
          </span>
        </div>
        <div
          style={{
            flex: 1,
            minWidth: 0,
            display: 'flex',
            alignItems: 'center',
            gap: 20,
            padding: '0 18px',
            fontSize: 10,
            letterSpacing: '0.16em',
            textTransform: 'uppercase',
            color: 'var(--color-neutral-600)',
          }}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: 7, whiteSpace: 'nowrap' }}>
            <span
              style={{
                width: 5,
                height: 5,
                borderRadius: '50%',
                background: backendUp ? 'var(--color-accent-300)' : '#e06b5c',
                animation: backendUp ? 'holo-breathe 2s ease-in-out infinite' : undefined,
              }}
            />
            <span style={{ color: backendUp ? 'var(--color-accent-300)' : '#e06b5c' }}>
              {backendUp ? 'Holotable live' : 'Holotable dark'}
            </span>
          </span>
          <span style={{ whiteSpace: 'nowrap' }}>
            Lattice <span style={{ color: 'var(--color-accent-300)' }}>{activity}</span>
          </span>
          <span style={{ whiteSpace: 'nowrap' }}>
            Firing <span style={{ color: 'var(--color-accent-400)' }}>{firingRate > 0 ? firingRate.toFixed(0) : '0'}</span> /s
          </span>
          <span style={{ whiteSpace: 'nowrap', marginLeft: 'auto', color: 'var(--color-neutral-600)' }}>
            {backendUp ? 'Live daemon' : 'Rehearsal · no daemon'}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', borderLeft: '1px solid rgba(182,130,53,0.34)' }}>
          <button
            onClick={() => setMicOn((v) => !v)}
            style={{
              padding: '9px 15px',
              fontSize: 9.5,
              letterSpacing: '0.2em',
              textTransform: 'uppercase',
              fontFamily: 'var(--font-heading)',
              fontWeight: 600,
              background: 'transparent',
              border: 0,
              borderRight: '1px solid rgba(182,130,53,0.34)',
              color: micOn ? 'var(--color-accent-300)' : 'var(--color-neutral-600)',
              cursor: 'pointer',
            }}
          >
            Auditory
          </button>
          <button
            onClick={() => setPaletteOpen(true)}
            style={{
              padding: '9px 15px',
              fontSize: 9.5,
              letterSpacing: '0.2em',
              textTransform: 'uppercase',
              fontFamily: 'var(--font-heading)',
              fontWeight: 600,
              background: 'transparent',
              border: 0,
              color: 'var(--color-neutral-600)',
              cursor: 'pointer',
            }}
          >
            ⌘K Directives
          </button>
        </div>
      </header>

      <div
        style={{
          flex: 1,
          minHeight: 0,
          display: 'grid',
          gridTemplateColumns: '232px minmax(0,1fr) 296px',
          gap: 13,
          zIndex: 2,
          perspective: '1400px',
        }}
      >
        <aside
          style={{
            minHeight: 0,
            overflowY: 'auto',
            display: 'flex',
            flexDirection: 'column',
            gap: 13,
            transform: 'rotateY(15deg)',
            transformOrigin: 'left center',
          }}
        >
          <div className="holo-panel" style={{ padding: '14px 15px 15px' }}>
            <div className="holo-corner holo-corner-tl" />
            <div className="holo-corner holo-corner-br" />
            <div className="holo-kicker" style={{ marginBottom: 11, display: 'flex', justifyContent: 'space-between' }}>
              <span>Contents</span>
              <span style={{ color: 'var(--color-accent)' }}>keys 1–0</span>
            </div>
            <nav>
              {SCREENS.map((s) => (
                <button
                  key={s.key}
                  className={`holo-nav-btn${screen === s.key ? ' active' : ''}`}
                  onClick={() => setScreen(s.key)}
                >
                  <span className="holo-nav-num">{s.num}</span>
                  {s.label}
                </button>
              ))}
            </nav>
          </div>
          <VitalsPanel />
          <ConduitsPanel onOpen={() => setScreen('connections')} />
        </aside>

        <section style={{ minHeight: 0, position: 'relative' }}>
          <div hidden={screen !== 'core'} style={{ position: 'absolute', inset: 0 }}>
            <CoreScreen
              onStreamingChange={setStreaming}
              onFiringRateChange={setFiringRate}
              voiceInput={voiceInput}
              onSpeakingChange={setSpeaking}
            />
          </div>
          {detailScreen}
        </section>

        <aside
          style={{
            minHeight: 0,
            overflowY: 'auto',
            display: 'flex',
            flexDirection: 'column',
            gap: 13,
            transform: 'rotateY(-15deg)',
            transformOrigin: 'right center',
          }}
        >
          <AuditoryPanel micOn={micOn} onToggleMic={() => setMicOn((v) => !v)} paused={speaking} />
          <ToolsPanel />
          <LedgerPanel />
          <AvoidedPanel />
        </aside>
      </div>

      <footer
        className="holo-panel holo-boot-in"
        style={{
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          gap: 20,
          padding: '7px 16px',
          fontSize: 9,
          letterSpacing: '0.18em',
          textTransform: 'uppercase',
          color: 'var(--color-neutral-600)',
          zIndex: 2,
        }}
      >
        <span style={{ color: 'var(--color-accent)' }}>Orion Mk IV</span>
        <span>Move to orbit the table</span>
        <span>Click for a pulse</span>
        <span style={{ marginLeft: 'auto' }}>⌘K Directives</span>
        <span style={{ color: 'var(--color-accent-300)' }}>Lattice {activity}</span>
      </footer>

      {paletteOpen && (
        <div
          onClick={() => setPaletteOpen(false)}
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 60,
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'center',
            paddingTop: '15vh',
            background: 'rgba(10,8,6,0.7)',
            backdropFilter: 'blur(6px)',
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              width: '100%',
              maxWidth: 520,
              border: '1px solid rgba(182,130,53,0.55)',
              background: 'rgba(26,23,19,0.97)',
            }}
            className="holo-boot-in"
          >
            {SCREENS.map((s) => (
              <button
                key={s.key}
                onClick={() => {
                  setScreen(s.key);
                  setPaletteOpen(false);
                }}
                style={{
                  width: '100%',
                  display: 'flex',
                  alignItems: 'baseline',
                  gap: 13,
                  padding: '9px 17px',
                  fontSize: 14,
                  textAlign: 'left',
                  border: 0,
                  cursor: 'pointer',
                  color: 'var(--color-neutral-300)',
                  background: 'transparent',
                }}
              >
                <span style={{ fontSize: 9, color: 'var(--color-accent)' }}>{s.num}</span>
                <span style={{ fontFamily: 'var(--font-heading)', fontSize: 18 }}>{s.label}</span>
                <span style={{ marginLeft: 'auto', fontSize: 9.5, color: 'var(--color-neutral-600)' }}>{s.digit}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default HolotableShell;
