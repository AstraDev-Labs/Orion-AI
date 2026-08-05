const SENTENCE_END = /[.!?](?:\s+|$)/;

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

export function pullSpeakableSentences(buffer: string): {
  sentences: string[];
  remainder: string;
} {
  const sentences: string[] = [];
  let rest = buffer;

  while (true) {
    const match = rest.match(SENTENCE_END);
    if (!match || match.index === undefined) {
      break;
    }
    const end = match.index + match[0].length;
    const sentence = rest.slice(0, end).trim();
    if (sentence.length >= 2) {
      sentences.push(sentence);
    }
    rest = rest.slice(end);
  }

  return { sentences, remainder: rest };
}

type SpeakHandler = (text: string) => void;

export class StreamingSpeechQueue {
  private buffer = '';
  private queue: string[] = [];
  private speaking = false;
  private stopped = false;

  constructor(
    private readonly speak: SpeakHandler,
    private readonly onSpeakingChange?: (speaking: boolean) => void,
  ) {}

  reset(): void {
    this.buffer = '';
    this.queue = [];
    this.speaking = false;
    this.stopped = false;
    this.onSpeakingChange?.(false);
  }

  stop(): void {
    this.stopped = true;
    this.queue = [];
    this.buffer = '';
    this.onSpeakingChange?.(false);
  }

  pushDelta(delta: string): void {
    if (this.stopped || !delta) return;
    this.buffer += delta;
    const { sentences, remainder } = pullSpeakableSentences(this.buffer);
    this.buffer = remainder;
    if (sentences.length) {
      this.queue.push(...sentences);
      void this.drain();
    }
  }

  flush(): void {
    if (this.stopped) return;
    const tail = this.buffer.trim();
    this.buffer = '';
    if (tail.length >= 2) {
      this.queue.push(tail);
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

  private async drain(): Promise<void> {
    if (this.speaking || this.stopped) return;
    this.speaking = true;
    this.onSpeakingChange?.(true);

    while (this.queue.length > 0 && !this.stopped) {
      const next = this.queue.shift();
      if (!next) continue;
      await new Promise<void>((resolve) => {
        // Voice AI disabled temporarily for testing per user request
        /*
        const audio = new Audio(`/v1/speech/tts?text=${encodeURIComponent(next)}`);
        
        audio.onended = () => resolve();
        audio.onerror = () => resolve();
        
        audio.play().catch(() => resolve());
        */
        resolve();
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
