import { getBase } from './api';

export type SpeechHealth = {
  available: boolean;
  backend?: string;
  reason?: string;
};

function parseErrorBody(body: string, status: number): string {
  const trimmed = body.trim();
  if (!trimmed) {
    return `Transcription failed (${status})`;
  }
  if (trimmed.startsWith('{')) {
    try {
      const parsed = JSON.parse(trimmed) as { detail?: string | unknown };
      if (typeof parsed.detail === 'string') {
        return parsed.detail;
      }
    } catch {
      // fall through to raw body
    }
  }
  return trimmed;
}

export async function fetchSpeechHealth(): Promise<SpeechHealth> {
  const base = getBase();
  try {
    const response = await fetch(`${base}/v1/speech/health`);
    if (!response.ok) {
      return { available: false, reason: `HTTP ${response.status}` };
    }
    return (await response.json()) as SpeechHealth;
  } catch (error) {
    return {
      available: false,
      reason: (error as Error).message || 'Speech backend unreachable',
    };
  }
}

export async function transcribeAudio(
  blob: Blob,
  language = 'en',
): Promise<string> {
  const base = getBase();
  const form = new FormData();
  const ext = blob.type.includes('webm') ? 'webm' : 'wav';
  form.append('file', blob, `utterance.${ext}`);
  form.append('language', language);

  const response = await fetch(`${base}/v1/speech/transcribe`, {
    method: 'POST',
    body: form,
  });

  const body = await response.text();

  if (!response.ok) {
    throw new Error(parseErrorBody(body, response.status));
  }

  try {
    const payload = JSON.parse(body) as { text?: string };
    return (payload.text || '').trim();
  } catch {
    throw new Error('Invalid transcription response from server');
  }
}
