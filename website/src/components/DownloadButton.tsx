import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { fetchLatestRelease, formatSize, type OrionRelease } from '../lib/release';
import { RELEASES_URL } from '../lib/site';

type Props = {
  label?: string;
  variant?: 'primary' | 'ghost';
  size?: 'md' | 'lg';
  requirementsHref: string;
};

/**
 * "Download for Windows". Every click opens the alpha notice first; the
 * installer only downloads after the visitor confirms they understand it is
 * early software.
 */
export default function DownloadButton({ label = 'Download for Windows', variant = 'primary', size = 'md', requirementsHref }: Props) {
  const [open, setOpen] = useState(false);
  const [agreed, setAgreed] = useState(false);
  const [release, setRelease] = useState<OrionRelease | null>(null);
  const [state, setState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const dialogRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();

  // Runs once per button; fetchLatestRelease shares one request across the page.
  const started = useRef(false);
  const load = useCallback(() => {
    if (started.current) return;
    started.current = true;
    setState('loading');
    fetchLatestRelease()
      .then((r) => {
        setRelease(r);
        setState('ready');
      })
      .catch(() => setState('error'));
  }, []);

  const close = useCallback(() => {
    setOpen(false);
    setAgreed(false);
    triggerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    load();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
      if (e.key === 'Tab' && dialogRef.current) {
        const focusables = dialogRef.current.querySelectorAll<HTMLElement>('button, a[href], input:not([disabled])');
        const list = Array.from(focusables).filter((el) => !el.hasAttribute('disabled'));
        if (!list.length) return;
        const first = list[0];
        const last = list[list.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener('keydown', onKey);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    requestAnimationFrame(() => dialogRef.current?.querySelector<HTMLElement>('input')?.focus());
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = previousOverflow;
    };
  }, [open, load, close]);

  const startDownload = () => {
    if (!agreed) return;
    if (release?.downloadUrl) {
      window.location.href = release.downloadUrl;
      close();
    } else {
      window.open(release?.pageUrl || RELEASES_URL, '_blank', 'noopener');
    }
  };

  const sizeClass = size === 'lg' ? ' text-base px-7 py-3.5' : '';
  const hasInstaller = Boolean(release?.downloadUrl);

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className={`btn ${variant === 'primary' ? 'btn-primary' : 'btn-ghost'}${sizeClass}`}
        onClick={() => setOpen(true)}
        onMouseEnter={load}
        onFocus={load}
      >
        <WindowsIcon />
        {label}
      </button>

      {open && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center p-4"
          style={{ background: 'rgb(1 4 12 / 0.78)', backdropFilter: 'blur(6px)' }}
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) close();
          }}
        >
          <div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            className="panel w-full max-w-lg text-left"
            style={{ background: 'linear-gradient(180deg, #0b1b3a, #060e22)', padding: '1.6rem 1.6rem 1.4rem' }}
          >
            <div className="flex items-start justify-between gap-4">
              <span className="badge-alpha">
                <span aria-hidden="true">⚠</span> Alpha software
              </span>
              <button type="button" onClick={close} aria-label="Close" className="text-[var(--color-muted)] hover:text-white text-xl leading-none px-1">
                ×
              </button>
            </div>

            <h2 id={titleId} className="mt-4 text-xl font-semibold text-white">
              Orion is in alpha. Expect bugs.
            </h2>
            <p className="mt-2 text-[0.95rem] leading-relaxed text-[var(--color-muted)]">
              This is an early build, shared so you can try Orion and help improve it. Before you install:
            </p>

            <ul className="mt-4 space-y-2.5 text-[0.93rem] leading-relaxed text-[var(--color-muted)]">
              <li className="flex gap-2.5">
                <Dot /> <span><strong className="text-white">Things will break.</strong> Replies can be wrong or slow, voice can mishear, and some features are unfinished.</span>
              </li>
              <li className="flex gap-2.5">
                <Dot /> <span><strong className="text-white">Windows will warn you.</strong> The installer isn't code-signed yet, so SmartScreen shows "Windows protected your PC". Choose <em>More info → Run anyway</em>.</span>
              </li>
              <li className="flex gap-2.5">
                <Dot /> <span><strong className="text-white">It's a big first install.</strong> Setup downloads the AI engine and models: about 12&nbsp;GB of free space and a stable internet connection.</span>
              </li>
              <li className="flex gap-2.5">
                <Dot /> <span><strong className="text-white">Windows 10/11, 64-bit only.</strong> <a className="text-[var(--color-cyan-soft)] underline underline-offset-2" href={requirementsHref}>Check your PC</a> first.</span>
              </li>
            </ul>

            <label className="mt-5 flex cursor-pointer items-start gap-3 rounded-xl border border-[var(--color-line)] bg-[rgb(10_23_49/0.6)] p-3 text-[0.92rem] text-[var(--color-text)]">
              <input
                type="checkbox"
                checked={agreed}
                onChange={(e) => setAgreed(e.target.checked)}
                className="mt-1 h-4 w-4 accent-[#38bdf8]"
              />
              <span>I understand Orion is alpha software with bugs, and I want to install it.</span>
            </label>

            <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
              <span className="text-xs text-[var(--color-faint)]">
                {state === 'loading' && 'Finding the latest build…'}
                {state === 'ready' && hasInstaller && `${release?.fileName} · ${formatSize(release?.sizeBytes ?? null)}`}
                {state === 'ready' && !hasInstaller && 'No installer is attached to a release yet.'}
                {state === 'error' && 'Could not reach GitHub. The button opens the releases page.'}
              </span>
              <div className="flex gap-2">
                <button type="button" className="btn btn-ghost" onClick={close}>
                  Cancel
                </button>
                <button type="button" className="btn btn-primary" disabled={!agreed} onClick={startDownload}>
                  {hasInstaller ? 'Download installer' : 'Open releases'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function Dot() {
  return <span aria-hidden="true" className="mt-[0.55rem] h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--color-cyan)]" />;
}

function WindowsIcon() {
  return (
    <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
      <path d="M3 5.1 10.4 4v7.1H3V5.1Zm0 13.8 7.4 1.1v-7H3v5.9ZM11.3 3.9 21 2.5v8.6h-9.7V3.9Zm0 16.2L21 21.5v-8.5h-9.7v7.1Z" />
    </svg>
  );
}
