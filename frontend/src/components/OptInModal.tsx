import { useState } from 'react';
import { useAppStore } from '../lib/store';

export function OptInModal() {
  const open = useAppStore((s) => s.optInModalOpen);
  const setOpen = useAppStore((s) => s.setOptInModalOpen);
  const markSeen = useAppStore((s) => s.markOptInModalSeen);
  const setOptIn = useAppStore((s) => s.setOptIn);
  const anonId = useAppStore((s) => s.optInAnonId);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');

  if (!open) return null;

  const close = () => {
    markSeen();
    setOpen(false);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="w-full max-w-sm rounded-xl border border-border-strong bg-surface p-6">
        <h2 className="text-sm font-semibold text-text mb-1">Share your savings</h2>
        <p className="text-xs text-text-muted mb-4">
          Optionally appear on the community leaderboard for tokens/energy saved by running locally.
        </p>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Display name"
          className="w-full mb-2 px-3 py-2 rounded-lg bg-surface-2 border border-border text-sm text-text placeholder:text-text-faint outline-none focus:border-accent"
        />
        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="Email (optional)"
          className="w-full mb-4 px-3 py-2 rounded-lg bg-surface-2 border border-border text-sm text-text placeholder:text-text-faint outline-none focus:border-accent"
        />
        <div className="flex gap-2">
          <button
            onClick={close}
            className="flex-1 px-3 py-2 rounded-lg border border-border text-sm text-text-muted hover:bg-white/5 transition-colors"
          >
            Not now
          </button>
          <button
            onClick={() => {
              setOptIn(true, name || `user-${anonId.slice(0, 6)}`, email);
              close();
            }}
            disabled={!name.trim()}
            className="flex-1 px-3 py-2 rounded-lg bg-accent text-white text-sm font-medium hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Join
          </button>
        </div>
      </div>
    </div>
  );
}
