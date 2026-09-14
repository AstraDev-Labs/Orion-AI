import { useEffect, useRef, useState } from 'react';
import './hud.css';
import orionLogo from '../assets/orion-logo.png';
import { getBase, getSetupStatus, isTauri, type SetupStatus } from '../lib/api';

/**
 * Startup screen shown until Orion can actually answer.
 *
 * Every step is read from a real signal -- the desktop app's boot status
 * (engine, model download, server) and the API's own health, model and voice
 * endpoints -- so it never shows progress that isn't happening. Works the same
 * on any machine: nothing here assumes a user, path or model.
 */

type StepState = 'waiting' | 'active' | 'done' | 'failed';

interface Step {
  key: string;
  label: string;
  state: StepState;
  detail: string;
}

const MIN_VISIBLE_MS = 900; // no flash on a warm start
const SLOW_HINT_MS = 45_000;

async function probe<T>(path: string, timeoutMs = 2500): Promise<T | null> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${getBase()}${path}`, { signal: controller.signal });
    if (!res.ok) return null;
    return (await res.json().catch(() => ({}))) as T;
  } catch {
    return null;
  } finally {
    window.clearTimeout(timer);
  }
}

export function LoadingScreen({ onReady }: { onReady: () => void }) {
  const [steps, setSteps] = useState<Step[]>(() => [
    { key: 'engine', label: 'Local AI engine', state: 'active', detail: 'Starting…' },
    { key: 'model', label: 'Language model', state: 'waiting', detail: '' },
    { key: 'server', label: 'Orion core', state: 'waiting', detail: '' },
    { key: 'voice', label: 'Voice', state: 'waiting', detail: '' },
  ]);
  const [error, setError] = useState('');
  const [slow, setSlow] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const startedRef = useRef(Date.now());
  const doneRef = useRef(false);

  useEffect(() => {
    // The static splash in index.html covers the moments before this renders.
    document.getElementById('boot-splash')?.remove();
    const slowTimer = window.setTimeout(() => setSlow(true), SLOW_HINT_MS);
    let alive = true;

    const tick = async () => {
      if (!alive || doneRef.current) return;
      const desktop: SetupStatus | null = isTauri() ? await getSetupStatus() : null;
      const health = await probe<Record<string, unknown>>('/health');
      const info = health ? await probe<{ model?: string; engine?: string }>('/v1/info') : null;
      const speech = health ? await probe<{ available?: boolean; backend?: string }>('/v1/speech/health', 4000) : null;
      if (!alive) return;

      const serverUp = Boolean(health && info?.model);
      const engineUp = serverUp || Boolean(desktop?.ollama_ready);
      const modelUp = serverUp || Boolean(desktop?.model_ready);
      const detail = desktop?.detail || '';

      const next: Step[] = [
        {
          key: 'engine',
          label: 'Local AI engine',
          state: engineUp ? 'done' : 'active',
          detail: engineUp ? info?.engine || 'Ready' : desktop?.phase === 'ollama' ? detail : 'Starting…',
        },
        {
          key: 'model',
          label: 'Language model',
          state: modelUp ? 'done' : engineUp ? 'active' : 'waiting',
          detail: modelUp ? info?.model || 'Ready' : engineUp ? detail || 'Loading…' : '',
        },
        {
          key: 'server',
          label: 'Orion core',
          state: serverUp ? 'done' : modelUp ? 'active' : 'waiting',
          detail: serverUp ? 'Online' : modelUp ? detail || 'Starting…' : '',
        },
        {
          key: 'voice',
          label: 'Voice',
          state: !serverUp ? 'waiting' : speech ? 'done' : 'active',
          // Voice is optional: a machine without speech support still starts.
          detail: !serverUp ? '' : speech?.available ? speech.backend || 'Ready' : speech ? 'Not installed (text only)' : 'Checking…',
        },
      ];
      setSteps(next);
      setError(desktop?.error || '');

      if (serverUp && speech !== null) {
        doneRef.current = true;
        const wait = Math.max(0, MIN_VISIBLE_MS - (Date.now() - startedRef.current));
        window.setTimeout(() => {
          setLeaving(true);
          window.setTimeout(onReady, 450);
        }, wait);
        return;
      }
      window.setTimeout(tick, serverUp ? 400 : 900);
    };
    void tick();
    return () => {
      alive = false;
      window.clearTimeout(slowTimer);
    };
  }, [onReady]);

  const doneCount = steps.filter((s) => s.state === 'done').length;

  return (
    <div
      className="holo-root"
      style={{
        position: 'fixed',
        inset: 0,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 100,
        opacity: leaving ? 0 : 1,
        transition: 'opacity 0.45s ease',
        background: 'radial-gradient(900px 700px at 50% 45%, #1c1811 0%, #100e0b 70%)',
      }}
      role="status"
      aria-live="polite"
    >
      <div style={{ width: 'min(440px, 88vw)', textAlign: 'center' }}>
        <img
          src={orionLogo}
          alt=""
          aria-hidden="true"
          className="orion-loader-logo"
          style={{ width: 132, height: 132, display: 'block', margin: '0 auto 18px', borderRadius: 28 }}
        />
        <div style={{ fontFamily: 'var(--font-heading)', fontSize: 38, letterSpacing: '0.42em', paddingLeft: '0.42em' }}>ORION</div>
        <div className="holo-kicker" style={{ marginTop: 6, marginBottom: 30 }}>
          Waking up on this computer
        </div>

        <div style={{ textAlign: 'left', display: 'flex', flexDirection: 'column', gap: 2 }}>
          {steps.map((s) => (
            <div
              key={s.key}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                padding: '9px 2px',
                borderBottom: '1px solid rgba(182,130,53,0.14)',
                opacity: s.state === 'waiting' ? 0.45 : 1,
                transition: 'opacity 0.3s',
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  flexShrink: 0,
                  background: s.state === 'done' ? 'var(--color-accent-300)' : 'transparent',
                  border: `1px solid ${s.state === 'waiting' ? 'rgba(182,130,53,0.35)' : 'var(--color-accent-300)'}`,
                  animation: s.state === 'active' ? 'holo-breathe 1.4s ease-in-out infinite' : undefined,
                }}
              />
              <span style={{ fontSize: 13.5, flex: 1 }}>{s.label}</span>
              <span
                style={{
                  fontSize: 11,
                  color: s.state === 'done' ? 'var(--color-accent-300)' : 'var(--color-neutral-600)',
                  fontStyle: s.state === 'done' ? 'normal' : 'italic',
                  maxWidth: 220,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
                title={s.detail}
              >
                {s.detail}
              </span>
            </div>
          ))}
        </div>

        <div style={{ height: 2, marginTop: 22, background: 'rgba(182,130,53,0.15)', overflow: 'hidden' }}>
          <div
            style={{
              height: '100%',
              width: `${(doneCount / steps.length) * 100}%`,
              background: 'var(--color-accent-300)',
              transition: 'width 0.5s ease',
            }}
          />
        </div>

        {error && (
          <div style={{ marginTop: 18, fontSize: 12.5, lineHeight: 1.6, color: '#e06b5c', textAlign: 'left' }}>
            {error}
          </div>
        )}
        {!error && slow && (
          <div style={{ marginTop: 18, fontSize: 12, lineHeight: 1.6, color: 'var(--color-neutral-600)', fontStyle: 'italic' }}>
            First start downloads the AI model, which can take several minutes on a slow connection.
          </div>
        )}
      </div>
    </div>
  );
}

export default LoadingScreen;
