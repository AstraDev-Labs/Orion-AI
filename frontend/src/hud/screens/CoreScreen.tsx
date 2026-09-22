import { useCallback, useEffect, useRef, useState } from 'react';
import { useAppStore } from '../../lib/store';
import { streamChat } from '../../lib/sse';
import { fetchSavingsSummary, fetchVitals, toolLabel } from '../api';
import { StreamingSpeechQueue, stripMarkdown } from '../../lib/voiceSpeech';
import { LATTICE_NODES } from '../holo/lattice';
import { getVoiceReplies } from '../../lib/voicePrefs';
import { getBase } from '../../lib/api';

function genId() {
  return Math.random().toString(36).slice(2);
}

/** The Core — live chat, real streaming via the same /v1/chat/completions used everywhere else. */
export function CoreScreen({
  onStreamingChange,
  onFiringRateChange,
  voiceInput,
  onSpeakingChange,
}: {
  onStreamingChange?: (s: boolean) => void;
  onFiringRateChange?: (tokPerSec: number) => void;
  /** A transcribed utterance from the HUD mic; each new id is sent once. */
  voiceInput?: { id: number; text: string } | null;
  /** True while a reply is being spoken aloud. */
  onSpeakingChange?: (speaking: boolean) => void;
}) {
  const [input, setInput] = useState('');
  const [streaming, setStreamingState] = useState(false);
  const setStreaming = useCallback(
    (s: boolean) => {
      setStreamingState(s);
      onStreamingChange?.(s);
    },
    [onStreamingChange],
  );
  const [content, setContent] = useState('');
  // While a spoken reply plays, only the words already voiced are shown, so the
  // text never runs seconds ahead of the voice. null = show the full reply.
  const [voicedText, setVoicedText] = useState<string | null>(null);
  // What Orion is doing before any words arrive ("Using web search…"), from
  // the agent's live tool events -- so a long tool run never looks frozen.
  const [activityNote, setActivityNote] = useState('');
  const [ttftMs, setTtftMs] = useState<number | null>(null);
  const [tokPerSec, setTokPerSec] = useState<number | null>(null);
  const startRef = useRef(0);

  // Real, computed from actual usage -- the same energy/cost estimation
  // methodology already used on the Reckoning screen and the right-rail
  // "Avoided" panel (see savings.py: compute_savings), not invented numbers.
  const [avoidedDollars, setAvoidedDollars] = useState<number | null>(null);
  const [totalTokens, setTotalTokens] = useState<number | null>(null);
  const [drawWatts, setDrawWatts] = useState<number | null>(null);
  // False once vitals have loaded without a power reading: no NVIDIA GPU (or
  // its sensor can't be read), so Draw says so instead of a bare dash.
  const [drawAvailable, setDrawAvailable] = useState(true);

  // Real per-session draw stats and energy, integrated client-side from
  // actual NVML samples polled every 5s -- not a mock "38W average, 71W
  // peak" narrative like the design source's, but the same shape of
  // sentence built from genuinely measured numbers.
  const drawSamplesRef = useRef<{ t: number; w: number }[]>([]);
  const kwhAccumRef = useRef(0);
  const [sessionStats, setSessionStats] = useState<{ avgW: number; peakW: number; kwh: number } | null>(null);

  useEffect(() => {
    fetchSavingsSummary()
      .then((s) => {
        setAvoidedDollars(s.per_provider.reduce((a, p) => a + p.total_cost, 0));
        setTotalTokens(s.total_tokens);
      })
      .catch(() => {});
    // Real NVML reading if this machine has an NVIDIA GPU; null (shown as
    // "—") otherwise, rather than a guessed number.
    const pollDraw = () =>
      fetchVitals()
        .then((v) => {
          setDrawWatts(v.draw_watts);
          setDrawAvailable(v.draw_watts != null);
          if (v.draw_watts == null) return;
          const now = Date.now();
          const samples = drawSamplesRef.current;
          const last = samples[samples.length - 1];
          if (last) {
            const hours = (now - last.t) / 3_600_000;
            kwhAccumRef.current += (last.w * hours) / 1000;
          }
          samples.push({ t: now, w: v.draw_watts });
          if (samples.length > 720) samples.shift(); // ~1hr at 5s cadence
          const avgW = samples.reduce((a, s) => a + s.w, 0) / samples.length;
          const peakW = Math.max(...samples.map((s) => s.w));
          setSessionStats({ avgW, peakW, kwh: kwhAccumRef.current });
        })
        .catch(() => {});
    pollDraw();
    const id = setInterval(pollDraw, 5000);
    return () => clearInterval(id);
  }, []);

  const selectedModel = useAppStore((s) => s.selectedModel);
  const activeId = useAppStore((s) => s.activeId);
  const createConversation = useAppStore((s) => s.createConversation);
  const addMessage = useAppStore((s) => s.addMessage);
  const messages = useAppStore((s) => s.messages);

  const speechQueueRef = useRef<StreamingSpeechQueue | null>(null);
  // Guards against a second send starting before React re-renders with
  // streaming=true (the `streaming` state in send's closure can be stale).
  const inFlightRef = useRef(false);

  // `fromMic` is set when the message came from the microphone.
  const send = useCallback(async (override?: string, fromMic = false) => {
    // Spoken for microphone questions, and for typed ones too while voice
    // replies are on (the default).
    const spoken = fromMic || getVoiceReplies();
    const text = (override ?? input).trim();
    if (!text || streaming || inFlightRef.current) return;
    inFlightRef.current = true;
    if (override === undefined) setInput('');
    setContent('');
    setVoicedText(spoken ? '' : null);
    setActivityNote('Thinking…');
    setTtftMs(null);
    setTokPerSec(null);

    let convId = activeId;
    if (!convId) convId = createConversation(selectedModel);
    addMessage(convId, { id: genId(), role: 'user', content: text, timestamp: Date.now() });

    const apiMessages = [...messages, { role: 'user' as const, content: text }].map((m) => ({
      role: m.role,
      content: m.content,
    }));

    speechQueueRef.current?.stop();
    let voiceStarted = false;
    const speechQueue = spoken
      ? new StreamingSpeechQueue(() => {}, onSpeakingChange, (chunk) => {
          voiceStarted = true;
          setVoicedText((shown) => (shown ? `${shown} ${chunk}` : chunk));
        })
      : null;
    speechQueueRef.current = speechQueue;
    // Words follow the voice, but the reply must never stay hidden: if the
    // voice hasn't started shortly after text arrives (slow or failed TTS,
    // blocked autoplay), show the text as it streams instead.
    let revealTimer: number | undefined;
    const armRevealFallback = () => {
      if (!speechQueue || revealTimer !== undefined) return;
      revealTimer = window.setTimeout(() => {
        if (!voiceStarted && speechQueueRef.current === speechQueue) setVoicedText(null);
      }, 2500);
    };

    setStreaming(true);
    startRef.current = Date.now();
    let acc = '';
    // Timing lives in locals, not state: the callback's copy of ttftMs was
    // stale, so TTFT was overwritten on every chunk of the first reply and
    // never set on later ones.
    let firstChunkAt = 0;
    let lastChunkAt = 0;
    let chunks = 0;
    let reportedTokens = 0;
    try {
      for await (const ev of streamChat({ model: selectedModel, messages: apiMessages, stream: true }, undefined)) {
        try {
          const data = JSON.parse(ev.data);
          if (ev.event === 'tool_call_start') {
            setActivityNote(`Using ${toolLabel(String(data.tool || data.tool_name || 'a tool')).toLowerCase()}…`);
            continue;
          }
          if (ev.event === 'tool_call_end' || ev.event === 'inference_start') {
            setActivityNote('Thinking…');
            continue;
          }
          if (ev.event) continue;
          const completionTokens = data.usage?.completion_tokens;
          if (typeof completionTokens === 'number' && completionTokens > 0) reportedTokens = completionTokens;
          const delta = data.choices?.[0]?.delta?.content;
          if (delta) {
            const now = Date.now();
            if (!firstChunkAt) {
              firstChunkAt = now;
              setTtftMs(now - startRef.current);
            }
            lastChunkAt = now;
            chunks += 1;
            acc += delta;
            armRevealFallback();
            speechQueue?.pushDelta(delta);
            setContent(acc);
            // Live rate over the generation itself (first to latest chunk), not
            // the wait before it; each streamed chunk is about one token.
            const genS = (now - firstChunkAt) / 1000;
            if (chunks >= 3 && genS >= 0.25) {
              const rate = (chunks - 1) / genS;
              setTokPerSec(rate);
              onFiringRateChange?.(rate);
            }
          }
          if (data.choices?.[0]?.finish_reason === 'stop') break;
        } catch {
          /* skip malformed chunk */
        }
      }
    } finally {
      if (firstChunkAt) {
        // Final figure: the engine's own token count when it reports one.
        const tokens = reportedTokens || chunks;
        const genS = (lastChunkAt - firstChunkAt) / 1000;
        if (genS >= 0.25 && tokens > 1) {
          setTokPerSec((tokens - 1) / genS);
        } else {
          // The reply arrived in one burst (e.g. after a tool ran): report the
          // average over the whole request rather than a meaningless spike.
          const totalS = (lastChunkAt - startRef.current) / 1000;
          if (totalS > 0) setTokPerSec(tokens / totalS);
        }
      }
      speechQueue?.flush();
      if (speechQueue) {
        // Once the voice finishes (or is interrupted), show the complete reply.
        void speechQueue.whenIdle().then(() => {
          if (speechQueueRef.current === speechQueue) setVoicedText(null);
        });
      }
      if (acc) addMessage(convId, { id: genId(), role: 'assistant', content: acc, timestamp: Date.now() });
      else if (speechQueue) setVoicedText(null);
      inFlightRef.current = false;
      setActivityNote('');
      setStreaming(false);
      onFiringRateChange?.(0);
    }
  }, [input, streaming, activeId, createConversation, selectedModel, addMessage, messages, onFiringRateChange, onSpeakingChange]);

  const sendRef = useRef(send);
  sendRef.current = send;
  const lastVoiceIdRef = useRef<number | null>(null);
  useEffect(() => {
    if (!voiceInput || voiceInput.id === lastVoiceIdRef.current) return;
    lastVoiceIdRef.current = voiceInput.id;
    void sendRef.current(voiceInput.text, true);
  }, [voiceInput]);

  // Greet the user once per launch, when the window is first on screen
  // (not while Orion starts hidden in the tray at login). The greeting comes
  // from the backend: the user's name and the real local time of day.
  useEffect(() => {
    let cancelled = false;
    const GREETED = 'orion-greeted';
    const greet = async () => {
      if (cancelled || document.visibilityState !== 'visible') return;
      try {
        if (sessionStorage.getItem(GREETED)) return;
        sessionStorage.setItem(GREETED, '1');
      } catch {
        /* no session storage: greet anyway */
      }
      try {
        const res = await fetch(`${getBase()}/v1/hud/greeting`);
        if (!res.ok || cancelled) return;
        const { text } = (await res.json()) as { text?: string };
        if (!text || cancelled || inFlightRef.current) return;
        setContent(text);
        if (getVoiceReplies()) {
          speechQueueRef.current?.stop();
          const queue = new StreamingSpeechQueue(() => {}, onSpeakingChange);
          speechQueueRef.current = queue;
          queue.pushDelta(text);
          queue.flush();
        }
      } catch {
        /* backend not reachable yet: skip the greeting rather than retry */
      }
    };
    void greet();
    document.addEventListener('visibilitychange', greet);
    return () => {
      cancelled = true;
      document.removeEventListener('visibilitychange', greet);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Stop talking if the Core is left mid-sentence.
  useEffect(() => () => speechQueueRef.current?.stop(), []);

  return (
    <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '20px 24px 0', textAlign: 'center' }} className="holo-boot-in">
        <div className="holo-kicker" style={{ marginBottom: 7, letterSpacing: '0.3em' }}>
          Core lattice · {LATTICE_NODES} nodes · {selectedModel || 'no model selected'}
        </div>
        <h1 style={{ fontSize: 'clamp(24px, 3vw, 40px)' }}>
          {streaming ? 'Thinking in the open' : 'Speak, or set a directive.'}
        </h1>
        {streaming && activityNote && !(voicedText || content) && (
          <div
            role="status"
            style={{ marginTop: 10, fontSize: 12.5, fontStyle: 'italic', color: 'var(--color-accent-300)' }}
          >
            {activityNote}
          </div>
        )}
        {!streaming && !content && sessionStats && sessionStats.kwh > 0 && (
          <p
            style={{
              maxWidth: 620,
              margin: '12px auto 0',
              fontSize: 13.5,
              lineHeight: 1.7,
              color: 'var(--color-neutral-400)',
            }}
          >
            Average draw was {sessionStats.avgW.toFixed(0)} W this session, peaking at{' '}
            {sessionStats.peakW.toFixed(0)} W. Local inference consumed {sessionStats.kwh.toFixed(3)} kWh
            {totalTokens ? ` across ${totalTokens.toLocaleString()} tokens` : ''}
            {avoidedDollars != null && avoidedDollars > 0
              ? ` — the same work against a hosted frontier model would have cost $${avoidedDollars.toFixed(2)}, and nothing left this machine.`
              : '.'}
          </p>
        )}
        {(content || streaming) && (
          <p
            style={{
              maxWidth: 620,
              margin: '12px auto 0',
              fontSize: 13.5,
              lineHeight: 1.7,
              color: 'var(--color-neutral-400)',
              whiteSpace: 'pre-wrap',
              textAlign: 'left',
            }}
          >
            {stripMarkdown(voicedText ?? content)}
            {(streaming || voicedText !== null) && (
              <span
                style={{
                  display: 'inline-block',
                  width: 6,
                  height: 13,
                  marginLeft: 3,
                  background: 'var(--color-accent-300)',
                  verticalAlign: 'middle',
                  animation: 'holo-caret 1.1s step-end infinite',
                }}
              />
            )}
          </p>
        )}
      </div>

      <div style={{ position: 'relative', flex: 1 }}>
        <div style={{ position: 'absolute', top: '30%', left: '9%', textAlign: 'left' }}>
          <div className="holo-kicker" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 14, height: 1, background: 'var(--color-neutral-600)' }} />
            Ttft
          </div>
          <div style={{ fontFamily: 'var(--font-heading)', fontSize: 26, color: 'var(--color-accent-300)' }}>
            {ttftMs !== null ? (ttftMs / 1000).toFixed(2) : '—'}
            <span style={{ fontSize: 12, color: 'var(--color-neutral-400)' }}> s</span>
          </div>
        </div>
        <div style={{ position: 'absolute', top: '30%', right: '9%', textAlign: 'right' }}>
          <div className="holo-kicker" style={{ display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'flex-end' }}>
            Throughput
            <span style={{ width: 14, height: 1, background: 'var(--color-neutral-600)' }} />
          </div>
          <div style={{ fontFamily: 'var(--font-heading)', fontSize: 26, color: 'var(--color-accent-300)' }}>
            {tokPerSec !== null ? tokPerSec.toFixed(1) : '—'}
            <span style={{ fontSize: 12, color: 'var(--color-neutral-400)' }}> tok/s</span>
          </div>
        </div>
        <div style={{ position: 'absolute', bottom: '24%', left: '9%', textAlign: 'left' }}>
          <div className="holo-kicker">Draw</div>
          {drawAvailable ? (
            <div style={{ fontFamily: 'var(--font-heading)', fontSize: 26, color: 'var(--color-accent-300)' }}>
              {drawWatts !== null ? drawWatts.toFixed(0) : '—'}
              <span style={{ fontSize: 12, color: 'var(--color-neutral-400)' }}> W</span>
            </div>
          ) : (
            <div
              title="Power draw is read from an NVIDIA graphics card's sensor. This PC doesn't have one Orion can read."
              style={{ fontFamily: 'var(--font-heading)', fontSize: 13, lineHeight: 1.35, marginTop: 6, color: 'var(--color-neutral-400)' }}
            >
              No GPU power
              <br />
              sensor
            </div>
          )}
        </div>
        <div style={{ position: 'absolute', bottom: '24%', right: '9%', textAlign: 'right' }}>
          <div className="holo-kicker">Avoided</div>
          <div style={{ fontFamily: 'var(--font-heading)', fontSize: 26, color: 'var(--color-accent-300)' }}>
            {avoidedDollars !== null ? `$${avoidedDollars.toFixed(2)}` : '—'}
          </div>
        </div>
      </div>

      <div style={{ marginTop: 'auto', padding: '0 24px 18px', display: 'flex', justifyContent: 'center' }}>
        <div
          className="holo-panel"
          style={{ width: '100%', maxWidth: 620, background: 'rgba(16,14,11,0.8)', borderColor: 'rgba(182,130,53,0.5)' }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 11, padding: '13px 15px' }}>
            <span style={{ color: 'var(--color-accent)' }}>›</span>
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder="Speak, or set a directive…"
              disabled={streaming}
              style={{
                flex: 1,
                minWidth: 0,
                background: 'transparent',
                border: 0,
                outline: 'none',
                fontSize: 14,
                color: 'var(--color-neutral-100)',
                fontFamily: 'var(--font-body)',
              }}
            />
            <button className="holo-ghost-btn" onClick={() => void send()} disabled={streaming || !input.trim()}>
              {streaming ? 'Working…' : 'Commit'}
            </button>
          </div>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 14,
              padding: '8px 15px',
              borderTop: '1px solid rgba(182,130,53,0.24)',
              fontSize: 9.5,
              letterSpacing: '0.14em',
              textTransform: 'uppercase',
              color: 'var(--color-neutral-600)',
            }}
          >
            <span style={{ color: 'var(--color-neutral-400)' }}>{selectedModel || 'no model selected'}</span>
            <span>Research</span>
            <span>Gestures</span>
            <span style={{ marginLeft: 'auto', color: 'var(--color-accent)' }}>⏎ commit</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default CoreScreen;
