import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { MessageSquare, Plus } from 'lucide-react';
import { useAppStore } from '../lib/store';

interface Item {
  id: string;
  label: string;
  hint?: string;
  icon: typeof MessageSquare;
  run: () => void;
}

export function CommandPalette() {
  const navigate = useNavigate();
  const setOpen = useAppStore((s) => s.setCommandPaletteOpen);
  const createConversation = useAppStore((s) => s.createConversation);
  const [query, setQuery] = useState('');
  const [index, setIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const close = () => setOpen(false);

  const items: Item[] = useMemo(
    () => [
      {
        id: 'new-chat',
        label: 'New chat',
        icon: Plus,
        run: () => {
          createConversation();
          navigate('/');
        },
      },
      { id: 'chat', label: 'Go to Chat', icon: MessageSquare, run: () => navigate('/') },
    ],
    [navigate, createConversation],
  );

  const filtered = items.filter((i) => i.label.toLowerCase().includes(query.toLowerCase()));

  const runSelected = (item?: Item) => {
    const target = item ?? filtered[index];
    if (!target) return;
    target.run();
    close();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[18vh] bg-black/60 backdrop-blur-sm animate-fade-in"
      onClick={close}
      onKeyDown={(e) => {
        if (e.key === 'Escape') close();
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          setIndex((i) => Math.min(i + 1, filtered.length - 1));
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault();
          setIndex((i) => Math.max(i - 1, 0));
        }
        if (e.key === 'Enter') {
          e.preventDefault();
          runSelected();
        }
      }}
    >
      <div
        className="w-full max-w-lg rounded-xl border border-border-strong bg-surface shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setIndex(0);
          }}
          placeholder="Type a command..."
          className="w-full px-4 py-3.5 bg-transparent text-sm text-text placeholder:text-text-faint outline-none border-b border-border"
        />
        <div className="max-h-72 overflow-y-auto py-1.5 scrollbar-none">
          {filtered.length === 0 && (
            <div className="px-4 py-6 text-center text-sm text-text-faint">No matches</div>
          )}
          {filtered.map((item, i) => (
            <button
              key={item.id}
              onClick={() => runSelected(item)}
              onMouseEnter={() => setIndex(i)}
              className={`w-full flex items-center gap-3 px-4 py-2 text-sm text-left transition-colors ${
                i === index ? 'bg-accent-subtle text-accent' : 'text-text-muted hover:bg-white/5'
              }`}
            >
              <item.icon size={15} strokeWidth={1.8} />
              {item.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
