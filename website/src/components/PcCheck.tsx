import { useEffect, useState } from 'react';

type Status = 'pass' | 'warn' | 'fail' | 'unknown';
type Row = { label: string; found: string; need: string; status: Status; note?: string };

type UAData = {
  platform: string;
  mobile: boolean;
  getHighEntropyValues: (hints: string[]) => Promise<{ platformVersion?: string; architecture?: string; bitness?: string }>;
};

/**
 * Reads what a web page is allowed to know about this computer and compares
 * it with what Orion needs. Browsers deliberately hide some details (exact
 * RAM above 8 GB, free disk space), so those are marked as "check yourself"
 * rather than guessed.
 */
export default function PcCheck() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [running, setRunning] = useState(false);

  const run = async () => {
    setRunning(true);
    const results: Row[] = [];
    const nav = navigator as Navigator & { userAgentData?: UAData; deviceMemory?: number };
    const ua = navigator.userAgent;

    // --- Operating system -----------------------------------------------------
    let osName = 'Unknown';
    let osStatus: Status = 'unknown';
    let arch = '';
    let bitness = '';
    let osNote: string | undefined;
    if (nav.userAgentData) {
      try {
        const hi = await nav.userAgentData.getHighEntropyValues(['platformVersion', 'architecture', 'bitness']);
        arch = hi.architecture ?? '';
        bitness = hi.bitness ?? '';
        if (nav.userAgentData.platform === 'Windows') {
          const major = parseInt((hi.platformVersion ?? '0').split('.')[0], 10);
          if (major >= 13) {
            osName = 'Windows 11';
            osStatus = 'pass';
          } else if (major >= 1) {
            osName = 'Windows 10';
            osStatus = 'pass';
            osNote = 'Needs version 1809 (October 2018 Update) or later.';
          } else {
            osName = 'An older Windows version';
            osStatus = 'fail';
          }
        } else {
          osName = nav.userAgentData.platform || 'Not Windows';
          osStatus = 'fail';
        }
      } catch {
        /* fall back to the user agent below */
      }
    }
    if (osStatus === 'unknown') {
      if (/Windows NT 10\.0/.test(ua)) {
        osName = 'Windows 10 or 11';
        osStatus = 'pass';
        osNote = 'Your browser cannot tell 10 from 11. Windows 10 needs version 1809 or later.';
      } else if (/Windows NT/.test(ua)) {
        osName = 'An older Windows version';
        osStatus = 'fail';
      } else if (/Mac OS X|Macintosh/.test(ua)) {
        osName = 'macOS';
        osStatus = 'fail';
      } else if (/Android|iPhone|iPad/.test(ua)) {
        osName = 'A phone or tablet';
        osStatus = 'fail';
        osNote = 'Open this page on the Windows PC you want to install Orion on.';
      } else if (/Linux/.test(ua)) {
        osName = 'Linux';
        osStatus = 'fail';
      }
    }
    if (osStatus === 'fail' && !osNote) osNote = 'The installer is for Windows only for now.';
    results.push({ label: 'Operating system', found: osName, need: 'Windows 10 (1809+) or Windows 11', status: osStatus, note: osNote });

    // --- Architecture ----------------------------------------------------------
    let archFound = 'Unknown';
    let archStatus: Status = 'unknown';
    let archNote: string | undefined;
    if (arch) {
      if (arch === 'x86' && bitness === '64') {
        archFound = '64-bit (x64)';
        archStatus = 'pass';
      } else if (arch === 'arm') {
        archFound = 'ARM';
        archStatus = 'warn';
        archNote = 'Orion is built for x64 PCs. It is untested on Windows on ARM.';
      } else {
        archFound = `${bitness || '32'}-bit`;
        archStatus = bitness === '64' ? 'pass' : 'fail';
      }
    } else if (/Win64|x64|WOW64/.test(ua)) {
      archFound = '64-bit';
      archStatus = 'pass';
    }
    results.push({ label: 'Processor type', found: archFound, need: '64-bit (x64)', status: archStatus, note: archNote });

    // --- Memory ----------------------------------------------------------------
    const mem = nav.deviceMemory;
    if (typeof mem === 'number') {
      const status: Status = mem >= 8 ? 'pass' : mem >= 4 ? 'warn' : 'fail';
      results.push({
        label: 'Memory (RAM)',
        found: mem >= 8 ? '8 GB or more' : `About ${mem} GB`,
        need: '8 GB recommended · 4 GB minimum',
        status,
        note:
          mem >= 8
            ? 'Browsers stop counting at 8 GB. With 8 GB or more, Orion uses its best everyday model (Qwen 3.5 4B).'
            : mem >= 4
              ? 'Orion will pick a smaller, less capable model to fit.'
              : 'Very little memory: replies will be slow and basic.',
      });
    } else {
      results.push({ label: 'Memory (RAM)', found: 'Hidden by your browser', need: '8 GB recommended · 4 GB minimum', status: 'unknown', note: 'Check in Settings → System → About.' });
    }

    // --- CPU -----------------------------------------------------------------------
    const cores = navigator.hardwareConcurrency || 0;
    results.push({
      label: 'Processor threads',
      found: cores ? `${cores}` : 'Unknown',
      need: '8 or more recommended',
      status: !cores ? 'unknown' : cores >= 8 ? 'pass' : cores >= 4 ? 'warn' : 'fail',
      note: cores && cores < 8 ? 'Orion runs, but replies and voice will be slower.' : undefined,
    });

    // --- GPU -----------------------------------------------------------------------
    let gpu = '';
    try {
      const gl = document.createElement('canvas').getContext('webgl');
      const ext = gl?.getExtension('WEBGL_debug_renderer_info');
      if (gl && ext) gpu = String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL));
    } catch {
      gpu = '';
    }
    const cleanGpu = gpu.replace(/^ANGLE \((.*)\)$/, '$1').replace(/ Direct3D.*$/, '').replace(/, or similar$/, '');
    const nvidia = /nvidia|geforce|rtx|gtx|quadro/i.test(gpu);
    results.push({
      label: 'Graphics',
      found: cleanGpu || 'Unknown',
      need: 'Optional · NVIDIA with 4 GB+ is faster',
      status: gpu ? (nvidia ? 'pass' : 'warn') : 'unknown',
      note: gpu && !nvidia ? 'Works without an NVIDIA GPU. Orion runs on the processor instead, which is slower.' : undefined,
    });

    // --- Microphone ---------------------------------------------------------------
    try {
      const devices = await navigator.mediaDevices?.enumerateDevices();
      const mics = devices?.filter((d) => d.kind === 'audioinput').length ?? 0;
      results.push({
        label: 'Microphone',
        found: mics ? 'Found' : 'None found',
        need: 'Needed for talking to Orion',
        status: mics ? 'pass' : 'warn',
        note: mics ? undefined : 'You can still type to Orion.',
      });
    } catch {
      results.push({ label: 'Microphone', found: 'Unknown', need: 'Needed for talking to Orion', status: 'unknown' });
    }

    // --- Disk --------------------------------------------------------------------
    results.push({
      label: 'Free disk space',
      found: 'Browsers cannot see this',
      need: '12 GB free on the install drive',
      status: 'unknown',
      note: 'Check in File Explorer → This PC. You can install to another drive during setup.',
    });

    setRows(results);
    setRunning(false);
  };

  useEffect(() => {
    void run();
  }, []);

  const verdict = (() => {
    if (!rows) return null;
    if (rows.some((r) => r.status === 'fail')) return { tone: 'fail' as Status, text: "This device can't run Orion's installer." };
    if (rows.some((r) => r.status === 'warn')) return { tone: 'warn' as Status, text: 'Orion should run here, with some limits.' };
    return { tone: 'pass' as Status, text: 'This PC looks ready for Orion.' };
  })();

  return (
    <div className="panel p-5 sm:p-7" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="eyebrow">Compatibility check</p>
          <h2 className="mt-2 text-xl font-semibold text-white sm:text-2xl">
            {verdict ? verdict.text : 'Checking this PC…'}
          </h2>
        </div>
        <button type="button" className="btn btn-ghost" onClick={() => void run()} disabled={running}>
          {running ? 'Checking…' : 'Check again'}
        </button>
      </div>
      <p className="mt-2 text-sm text-[var(--color-faint)]">
        Runs only in your browser; nothing is sent anywhere. Browsers hide some details, so treat this as a guide, not a guarantee.
      </p>

      <div className="mt-6 overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-left text-sm">
          <thead>
            <tr className="text-[var(--color-faint)]">
              <th className="py-2 pr-4 font-medium">Check</th>
              <th className="py-2 pr-4 font-medium">This device</th>
              <th className="py-2 pr-4 font-medium">Orion needs</th>
              <th className="py-2 font-medium">Result</th>
            </tr>
          </thead>
          <tbody>
            {(rows ?? []).map((r) => (
              <tr key={r.label} className="border-t border-[var(--color-line)] align-top">
                <td className="py-3 pr-4 font-medium text-white">{r.label}</td>
                <td className="py-3 pr-4 text-[var(--color-text)]">
                  {r.found}
                  {r.note && <div className="mt-1 text-xs leading-relaxed text-[var(--color-faint)]">{r.note}</div>}
                </td>
                <td className="py-3 pr-4 text-[var(--color-muted)]">{r.need}</td>
                <td className="py-3">
                  <StatusPill status={r.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StatusPill({ status }: { status: Status }) {
  const map: Record<Status, { text: string; color: string; bg: string }> = {
    pass: { text: 'Ready', color: '#6ee7b7', bg: 'rgb(52 211 153 / 0.12)' },
    warn: { text: 'Limited', color: '#fcd34d', bg: 'rgb(251 191 36 / 0.12)' },
    fail: { text: 'Not supported', color: '#fca5a5', bg: 'rgb(248 113 113 / 0.12)' },
    unknown: { text: 'Check yourself', color: '#a5b4cf', bg: 'rgb(148 163 184 / 0.12)' },
  };
  const s = map[status];
  return (
    <span className="inline-flex whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold" style={{ color: s.color, background: s.bg }}>
      {s.text}
    </span>
  );
}
