import { useEffect, useState } from 'react';

/**
 * Whether Orion reads its replies aloud. On by default: replies used to be
 * spoken only when the question came from the microphone, so a typed question
 * got a silent answer and the voice seemed broken.
 */
const KEY = 'orion-voice-replies';
const EVENT = 'orion-voice-replies-change';

export function getVoiceReplies(): boolean {
  try {
    return localStorage.getItem(KEY) !== 'off';
  } catch {
    return true;
  }
}

export function setVoiceReplies(on: boolean): void {
  try {
    localStorage.setItem(KEY, on ? 'on' : 'off');
  } catch {
    /* storage unavailable: the choice lasts for this session only */
  }
  window.dispatchEvent(new CustomEvent(EVENT, { detail: on }));
}

export function useVoiceReplies(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(getVoiceReplies);
  useEffect(() => {
    const sync = () => setOn(getVoiceReplies());
    window.addEventListener(EVENT, sync);
    return () => window.removeEventListener(EVENT, sync);
  }, []);
  return [on, setVoiceReplies];
}
