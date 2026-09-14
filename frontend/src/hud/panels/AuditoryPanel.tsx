import { useEffect, useRef, useState } from 'react';
import { useVoiceReplies } from '../../lib/voicePrefs';

/** Right-rail Auditory panel: a real microphone waveform (getUserMedia), not a mock. */
export function AuditoryPanel({
  micOn,
  onToggleMic,
  paused = false,
}: {
  micOn: boolean;
  onToggleMic: () => void;
  /** Release the microphone while Orion is speaking. An open mic stream makes
   * Windows switch audio into a lower-quality communications mode (and a
   * Bluetooth headset into its hands-free profile), which is what made
   * replies sound muffled whenever the mic was on. */
  paused?: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const rafRef = useRef<number | null>(null);
  const [error, setError] = useState('');
  const [voiceReplies, setVoiceReplies] = useVoiceReplies();

  useEffect(() => {
    if (!micOn || paused) return;
    let cancelled = false;
    let ctxAudio: AudioContext | null = null;

    (async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        ctxAudio = new AudioContext();
        const source = ctxAudio.createMediaStreamSource(stream);
        const analyser = ctxAudio.createAnalyser();
        analyser.fftSize = 1024;
        source.connect(analyser);
        const buffer = new Uint8Array(analyser.frequencyBinCount);
        const canvas = canvasRef.current;
        const ctx = canvas?.getContext('2d');

        const draw = () => {
          rafRef.current = requestAnimationFrame(draw);
          if (!canvas || !ctx) return;
          const { width, height } = canvas;
          analyser.getByteTimeDomainData(buffer);
          ctx.clearRect(0, 0, width, height);
          ctx.lineWidth = 1.5;
          ctx.strokeStyle = '#facb8d';
          ctx.beginPath();
          const slice = width / buffer.length;
          let x = 0;
          for (let i = 0; i < buffer.length; i++) {
            const v = buffer[i] / 128.0;
            const y = (v * height) / 2;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
            x += slice;
          }
          ctx.stroke();
        };
        draw();
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Microphone unavailable');
      }
    })();

    return () => {
      cancelled = true;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      ctxAudio?.close().catch(() => {});
    };
  }, [micOn, paused]);

  return (
    <div className="holo-panel" style={{ padding: '13px 14px 12px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }} className="holo-kicker">
        <span>Auditory</span>
        <button
          onClick={onToggleMic}
          style={{
            background: 'transparent',
            border: 0,
            cursor: 'pointer',
            color: micOn ? 'var(--color-accent-300)' : 'var(--color-neutral-600)',
            fontSize: 9,
            letterSpacing: '0.16em',
            textTransform: 'uppercase',
          }}
        >
          {micOn ? (error ? 'Error' : 'Live') : 'Off — click to listen'}
        </button>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }} className="holo-kicker">
        <span>Voice replies</span>
        <button
          onClick={() => setVoiceReplies(!voiceReplies)}
          aria-pressed={voiceReplies}
          style={{
            background: 'transparent',
            border: 0,
            cursor: 'pointer',
            color: voiceReplies ? 'var(--color-accent-300)' : 'var(--color-neutral-600)',
            fontSize: 9,
            letterSpacing: '0.16em',
            textTransform: 'uppercase',
          }}
        >
          {voiceReplies ? 'On' : 'Off — click to hear replies'}
        </button>
      </div>
      <canvas ref={canvasRef} width={260} height={64} style={{ width: '100%', height: 60, display: 'block' }} />
      <div
        style={{
          marginTop: 11,
          border: '1px solid rgba(182,130,53,0.22)',
          padding: 5,
        }}
      >
        <div
          style={{
            height: 70,
            backgroundImage:
              'repeating-linear-gradient(135deg, rgba(182,130,53,0.14) 0 6px, transparent 6px 12px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontFamily: 'ui-monospace, monospace',
            fontSize: 9.5,
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            color: 'var(--color-neutral-400)',
          }}
        >
          Optic feed · offline
        </div>
      </div>
    </div>
  );
}

export default AuditoryPanel;
