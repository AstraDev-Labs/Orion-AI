import { useEffect, useState } from 'react';
import {
  getPendingClipboardText,
  markClipboardSeen,
  closeClipboardPanel,
  runClipboardAction,
  type ClipboardActionKind,
} from '../lib/api';

const ACTIONS: { key: ClipboardActionKind; label: string }[] = [
  { key: 'translate', label: 'Translate' },
  { key: 'summarize', label: 'Summarize' },
  { key: 'explain', label: 'Explain' },
  { key: 'fix', label: 'Fix' },
];

/**
 * Standalone panel rendered in its own small always-on-top Tauri window
 * whenever new text is copied to the clipboard. See main.tsx for the
 * `?panel=clipboard` entry-point branch and src-tauri/src/lib.rs for the
 * clipboard watcher that creates this window.
 */
export function ClipboardPanel() {
  const [text, setText] = useState('');
  const [action, setAction] = useState<ClipboardActionKind | null>(null);
  const [result, setResult] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    getPendingClipboardText().then(setText);
  }, []);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') void closeClipboardPanel();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const runAction = async (kind: ClipboardActionKind) => {
    setAction(kind);
    setLoading(true);
    setError('');
    setResult('');
    try {
      const out = await runClipboardAction(text, kind);
      setResult(out);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.');
    } finally {
      setLoading(false);
    }
  };

  const copyResult = async () => {
    try {
      await navigator.clipboard.writeText(result);
      await markClipboardSeen(result);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard write can fail silently on some platforms — non-critical */
    }
  };

  const reset = () => {
    setAction(null);
    setResult('');
    setError('');
  };

  return (
    <div className="w-screen h-screen bg-surface text-text border border-border-strong rounded-lg overflow-hidden flex flex-col select-none">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border bg-surface-2 cursor-default">
        <span className="text-xs font-medium text-text-muted">ORION</span>
        <button
          onClick={() => void closeClipboardPanel()}
          className="text-text-faint hover:text-text text-xs px-1.5 py-0.5 rounded hover:bg-white/5"
          aria-label="Close"
        >
          ✕
        </button>
      </div>

      <div className="px-3 pt-2 pb-1">
        <p className="text-xs text-text-faint line-clamp-2">{text || 'No text copied.'}</p>
      </div>

      {!action && (
        <div className="grid grid-cols-2 gap-1.5 px-3 py-2">
          {ACTIONS.map((a) => (
            <button
              key={a.key}
              onClick={() => void runAction(a.key)}
              className="text-sm py-1.5 rounded-md bg-surface-2 hover:bg-white/10 border border-border text-text transition-colors"
            >
              {a.label}
            </button>
          ))}
        </div>
      )}

      {action && (
        <div className="flex-1 min-h-0 flex flex-col px-3 pb-2">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-xs font-medium text-accent">
              {ACTIONS.find((a) => a.key === action)?.label}
            </span>
            <button
              onClick={reset}
              className="text-xs text-text-faint hover:text-text"
            >
              ← Back
            </button>
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto text-sm leading-relaxed rounded-md bg-surface-2 border border-border p-2">
            {loading && <span className="text-text-faint">Thinking…</span>}
            {error && <span className="text-red-400">{error}</span>}
            {!loading && !error && result}
          </div>

          {!loading && result && (
            <button
              onClick={() => void copyResult()}
              className="mt-1.5 text-xs py-1.5 rounded-md bg-accent/20 hover:bg-accent/30 text-accent border border-accent/30 transition-colors"
            >
              {copied ? 'Copied!' : 'Copy result'}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
