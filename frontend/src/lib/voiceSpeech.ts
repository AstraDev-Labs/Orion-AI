import { getBase } from './api';
import { attachAudioElement, resetVoiceLevel } from './voiceLevel';

// A terminator only counts once whitespace follows it. Matching end-of-buffer
// too split mid-token while streaming ("12345678@example." before "edu"
// arrived, or a word before its closing backtick); flush() speaks the tail.
const SENTENCE_END = /[.!?]+\s+/;

const HEAVY_VOICE_MODEL = /(:\d+b\b|14b|70b|72b|32b|34b|coder:)/i;
const VOICE_CHAT_MODEL_PREFS = [
  'phi3:mini',
  'llama3.2:1b',
  'llama3.2:3b',
  'gemma2:2b',
  'qwen2.5:3b',
  'qwen2.5:1.5b',
];

/** Pick a small local model for voice chat (avoids OOM with Whisper + 14B). */
export function pickVoiceChatModel(
  modelIds: string[],
  selected: string,
  serverDefault: string,
): string {
  const match = (hint: string) =>
    modelIds.find((id) => id === hint || id.includes(hint));

  if (selected && !HEAVY_VOICE_MODEL.test(selected) && match(selected)) {
    return selected;
  }

  for (const pref of VOICE_CHAT_MODEL_PREFS) {
    const hit = match(pref);
    if (hit) return hit;
  }

  if (serverDefault && match(serverDefault)) return serverDefault;
  return modelIds[0] || selected || '';
}

// Clause boundary: a comma, semicolon, colon or dash followed by a space.
const CLAUSE_END = /[,;:—–](?:\s+)/g;
// Kokoro on CPU takes time proportional to text length, so the first spoken
// chunk is cut at the first clause once it has a few words: the voice starts
// while the model is still writing the rest of the sentence.
const FIRST_CHUNK_MIN_WORDS = 3;
// Later chunks split at a clause only when a sentence runs long, so one slow
// synthesis never holds up playback for a whole paragraph-length sentence.
const LONG_CHUNK_CHARS = 140;

function splitAtClause(text: string, minWords: number, minChars: number): number {
  CLAUSE_END.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = CLAUSE_END.exec(text)) !== null) {
    const end = match.index + match[0].length;
    const head = text.slice(0, end).trim();
    if (head.split(/\s+/).length >= minWords && head.length >= minChars) return end;
  }
  return -1;
}

export function pullSpeakableSentences(
  buffer: string,
  isFirstChunk = false,
): {
  sentences: string[];
  remainder: string;
} {
  const sentences: string[] = [];
  let rest = buffer;
  let first = isFirstChunk;

  while (true) {
    const match = rest.match(SENTENCE_END);
    const sentenceEnd =
      match && match.index !== undefined ? match.index + match[0].length : -1;
    const searchIn = sentenceEnd >= 0 ? rest.slice(0, sentenceEnd) : rest;
    const clauseEnd = first
      ? splitAtClause(searchIn, FIRST_CHUNK_MIN_WORDS, 0)
      : searchIn.length > LONG_CHUNK_CHARS
        ? splitAtClause(searchIn, FIRST_CHUNK_MIN_WORDS, 40)
        : -1;
    const end = clauseEnd >= 0 ? clauseEnd : sentenceEnd;
    if (end < 0) break;
    const sentence = rest.slice(0, end).trim();
    if (sentence.length >= 2) {
      sentences.push(sentence);
      first = false;
    }
    rest = rest.slice(end);
  }

  return { sentences, remainder: rest };
}

/** Strip markdown the model emits so it is never read aloud or shown raw. */
export function stripMarkdown(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/\*\*([^*]*)\*\*/g, '$1')
    .replace(/__([^_]*)__/g, '$1')
    .replace(/(^|\s)[*_]([^*_\n]+)[*_](?=\s|[.,!?;:]|$)/g, '$1$2')
    .replace(/\*\*|__/g, '')
    .replace(/^\s{0,3}#{1,6}\s+/gm, '')
    .replace(/^\s{0,3}>\s?/gm, '')
    .replace(/^\s*[-*•]\s+/gm, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
}

const DIGIT_WORDS = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine'];

/** Read a run of characters out one by one: "2410" -> "two four one zero". */
function spellOut(token: string): string {
  return token
    .split('')
    .map((ch) => (/\d/.test(ch) ? DIGIT_WORDS[Number(ch)] : ch === '.' ? 'dot' : ch))
    .join(' ');
}

/**
 * Turn display text into what the voice should actually say: no markdown
 * symbols, and emails/URLs pronounced the way a person reads them aloud
 * ("12345678@example.edu" -> "one two three four five six seven eight at example
 * dot edu") instead of as one long number.
 */
export function toSpeechText(text: string): string {
  return stripMarkdown(text)
    .replace(/https?:\/\/(www\.)?/gi, '')
    .replace(/([A-Za-z0-9._%+-]+)@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)/g, (_m, local: string, domain: string) => {
      const localSpoken = /\d{3,}/.test(local) ? spellOut(local) : local.replace(/\./g, ' dot ');
      return `${localSpoken} at ${domain.split('.').join(' dot ')}`;
    })
    .replace(/[—–]/g, ', ')
    .replace(/[*_#`~|<>]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

type SpeakHandler = (text: string) => void;

// Sentences synthesized ahead of the one currently playing. Previously each
// sentence was only requested after the previous one FINISHED playing, so every
// gap between sentences was a full synthesis run (~2-3s with Kokoro). Two ahead
// keeps the next sentence ready without piling concurrent jobs onto the CPU.
const PREFETCH_AHEAD = 2;

type QueuedSentence = { text: string; audio?: Promise<string | null> };

/** Called as each chunk starts playing, with that chunk's display text. */
type ChunkStartHandler = (text: string) => void;

export class StreamingSpeechQueue {
  private buffer = '';
  private queue: QueuedSentence[] = [];
  private controller = new AbortController();
  private speaking = false;
  private stopped = false;
  private currentAudio: HTMLAudioElement | null = null;
  private startedSpeaking = false;

  constructor(
    private readonly speak: SpeakHandler,
    private readonly onSpeakingChange?: (speaking: boolean) => void,
    private readonly onChunkStart?: ChunkStartHandler,
  ) {
    void this.speak; // reserved for a future non-HTTP TTS backend
  }

  reset(): void {
    this.controller.abort();
    this.controller = new AbortController();
    this.buffer = '';
    this.queue = [];
    this.speaking = false;
    this.stopped = false;
    this.startedSpeaking = false;
    this.onSpeakingChange?.(false);
  }

  stop(): void {
    this.stopped = true;
    this.controller.abort();
    this.queue = [];
    this.buffer = '';
    this.currentAudio?.pause();
    this.currentAudio = null;
    resetVoiceLevel();
    this.onSpeakingChange?.(false);
  }

  pushDelta(delta: string): void {
    if (this.stopped || !delta) return;
    this.buffer += delta;
    const { sentences, remainder } = pullSpeakableSentences(this.buffer, !this.startedSpeaking);
    this.buffer = remainder;
    if (sentences.length) {
      this.startedSpeaking = true;
      this.queue.push(...sentences.map((text) => ({ text })));
      this.prefetch();
      void this.drain();
    }
  }

  flush(): void {
    if (this.stopped) return;
    const tail = this.buffer.trim();
    this.buffer = '';
    if (tail.length >= 2) {
      this.queue.push({ text: tail });
      this.prefetch();
      void this.drain();
    } else if (!this.speaking && this.queue.length === 0) {
      this.onSpeakingChange?.(false);
    }
  }

  whenIdle(): Promise<void> {
    return new Promise((resolve) => {
      const check = () => {
        if (this.stopped || (!this.speaking && this.queue.length === 0)) {
          resolve();
          return;
        }
        window.setTimeout(check, 80);
      };
      check();
    });
  }

  /** Start synthesis for the next few queued sentences that have none yet. */
  private prefetch(): void {
    for (const item of this.queue.slice(0, PREFETCH_AHEAD)) {
      if (!item.audio) item.audio = this.synthesize(toSpeechText(item.text));
    }
  }

  /** Fetch one sentence's audio; resolves to an object URL, or null. */
  private async synthesize(text: string): Promise<string | null> {
    if (!text) return null;
    try {
      const res = await fetch(`${getBase()}/v1/speech/tts?text=${encodeURIComponent(text)}`, {
        signal: this.controller.signal,
      });
      if (!res.ok) return null;
      return URL.createObjectURL(await res.blob());
    } catch {
      return null; // aborted by stop(), or the request failed
    }
  }

  private async drain(): Promise<void> {
    if (this.speaking || this.stopped) return;
    this.speaking = true;
    this.onSpeakingChange?.(true);

    while (this.queue.length > 0 && !this.stopped) {
      const next = this.queue.shift();
      if (!next) continue;
      this.prefetch(); // keep the following sentences synthesizing meanwhile
      const url = await (next.audio ?? this.synthesize(toSpeechText(next.text)));
      if (this.stopped) {
        if (url) URL.revokeObjectURL(url);
        break;
      }
      // Reveal the words as they are spoken, so text and voice stay in step.
      this.onChunkStart?.(next.text);
      if (!url) continue;
      await new Promise<void>((resolve) => {
        // A same-origin blob URL, so the analyser in lib/voiceLevel.ts can read
        // the samples without any CORS configuration.
        const audio = new Audio();
        attachAudioElement(audio);
        audio.src = url;
        this.currentAudio = audio;
        const done = () => {
          URL.revokeObjectURL(url);
          resolve();
        };
        audio.onended = done;
        audio.onerror = done;
        audio.play().catch(done);
      });
    }

    this.speaking = false;
    if (!this.stopped && this.queue.length > 0) {
      void this.drain();
    } else if (!this.stopped) {
      this.onSpeakingChange?.(false);
    }
  }
}

export function primeSpeechVoices(): void {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) return;
  window.speechSynthesis.getVoices();
  window.speechSynthesis.onvoiceschanged = () => {
    window.speechSynthesis.getVoices();
  };
}
