/**
 * Live amplitude of whatever Orion is currently saying.
 *
 * The Core visual reacts to real TTS output rather than a synthetic loop: each
 * `<audio>` element the speech queue creates is routed through a shared
 * AnalyserNode, and `getVoiceLevel()` returns the smoothed RMS of the samples
 * actually being played.
 *
 * Two details this depends on, both easy to get wrong:
 *
 * - `crossOrigin` must be set *before* `src`. In the Tauri build the API lives
 *   on a different origin from the webview, so without it the element's audio
 *   is opaque and the analyser reads silence. The server already allows the
 *   Tauri and dev origins (see server/app.py's CORSMiddleware).
 * - `createMediaElementSource` *reroutes* the element's output into the graph.
 *   If the graph doesn't reach `destination`, playback goes silent. So the
 *   analyser is connected to the destination before any source is attached,
 *   and attachment failures are swallowed so audio keeps playing unanalysed.
 */

let ctx: AudioContext | null = null;
let analyser: AnalyserNode | null = null;
let samples: Uint8Array | null = null;
let smoothed = 0;

// createMediaElementSource may be called at most once per element.
const attached = new WeakSet<HTMLMediaElement>();

function ensureGraph(): boolean {
  if (analyser) return true;
  try {
    const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) return false;
    ctx = new Ctor();
    analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    analyser.smoothingTimeConstant = 0.7;
    samples = new Uint8Array(analyser.fftSize);
    // Connect to the speakers first — see the note above about rerouting.
    analyser.connect(ctx.destination);
    return true;
  } catch {
    ctx = null;
    analyser = null;
    samples = null;
    return false;
  }
}

/** Route one audio element through the analyser. Safe to call repeatedly. */
export function attachAudioElement(el: HTMLAudioElement): void {
  if (attached.has(el)) return;
  if (!ensureGraph() || !ctx || !analyser) return;
  try {
    const source = ctx.createMediaElementSource(el);
    source.connect(analyser);
    attached.add(el);
    if (ctx.state === 'suspended') void ctx.resume();
  } catch {
    // Element stays on the default output path and simply isn't analysed.
  }
}

/**
 * Smoothed speaking level, 0..1.
 *
 * Fast attack and slow release: syllable onsets register immediately, but the
 * visual doesn't strobe on the gaps between words.
 */
export function getVoiceLevel(): number {
  if (!analyser || !samples) return 0;
  if (ctx && ctx.state === 'suspended') return 0;

  analyser.getByteTimeDomainData(samples);
  let sum = 0;
  for (let i = 0; i < samples.length; i++) {
    const v = (samples[i] - 128) / 128;
    sum += v * v;
  }
  // Speech RMS sits low (~0.05–0.25); scale so normal speech spans the range.
  const level = Math.min(1, Math.sqrt(sum / samples.length) * 3.4);
  smoothed += (level - smoothed) * (level > smoothed ? 0.45 : 0.10);
  return smoothed;
}

/** True when a real analyser is running, so callers can tell live data from a fallback. */
export function hasVoiceAnalyser(): boolean {
  return analyser !== null && ctx?.state === 'running';
}

/** Drop the level immediately — called when speech is stopped mid-sentence. */
export function resetVoiceLevel(): void {
  smoothed = 0;
}
