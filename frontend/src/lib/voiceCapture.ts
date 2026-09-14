export type VoiceCaptureOptions = {
  silenceMs?: number;
  minSpeechMs?: number;
  maxMs?: number;
  speechThreshold?: number;
};

/** Mic settings for speech recognition: the browser's own echo cancellation,
 * noise suppression and auto-gain, mono. Without them a quiet or distant voice
 * reached Whisper under room noise ("can you hear me" came back as "feel"). */
export const SPEECH_AUDIO_CONSTRAINTS: MediaTrackConstraints = {
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true,
  channelCount: 1,
};

export type VoiceCaptureHandle = {
  stop: () => void;
  cancel: () => void;
};

/** Record mic audio and stop automatically after the user pauses. */
export async function recordUntilSilence(
  stream: MediaStream,
  onComplete: (blob: Blob) => void,
  options: VoiceCaptureOptions = {},
): Promise<VoiceCaptureHandle> {
  const silenceMs = options.silenceMs ?? 1200;
  const minSpeechMs = options.minSpeechMs ?? 400;
  const maxMs = options.maxMs ?? 20000;
  const speechThreshold = options.speechThreshold ?? 0.018;

  const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
    ? 'audio/webm;codecs=opus'
    : 'audio/webm';

  const chunks: Blob[] = [];
  let cancelled = false;
  let speechMs = 0;
  let silentMs = 0;

  // Opus at the browser default (~32 kbps) audibly smears consonants; speech
  // recognition is noticeably better at 96 kbps and the clips are tiny anyway.
  const recorder = new MediaRecorder(stream, { mimeType, audioBitsPerSecond: 96000 });
  const audioContext = new AudioContext();
  const source = audioContext.createMediaStreamSource(stream);
  const analyser = audioContext.createAnalyser();
  analyser.fftSize = 2048;
  source.connect(analyser);
  const samples = new Uint8Array(analyser.fftSize);

  const cleanup = () => {
    window.clearInterval(vadTimer);
    window.clearTimeout(maxTimer);
    void audioContext.close();
  };

  recorder.ondataavailable = (event) => {
    if (event.data.size > 0) chunks.push(event.data);
  };

  recorder.onstop = () => {
    cleanup();
    if (cancelled) return;
    // A recording that never contained speech (the 20 s cap hit in a quiet
    // room) is not sent: Whisper invents words from pure noise.
    if (speechMs < minSpeechMs) {
      onComplete(new Blob([], { type: mimeType }));
      return;
    }
    const blob = new Blob(chunks, { type: mimeType });
    onComplete(blob);
  };

  const getRms = (): number => {
    analyser.getByteTimeDomainData(samples);
    let sum = 0;
    for (let i = 0; i < samples.length; i += 1) {
      const sample = (samples[i] - 128) / 128;
      sum += sample * sample;
    }
    return Math.sqrt(sum / samples.length);
  };

  recorder.start(200);
  const vadTimer = window.setInterval(() => {
    const rms = getRms();
    if (rms >= speechThreshold) {
      speechMs += 200;
      silentMs = 0;
      return;
    }
    silentMs += 200;
    if (speechMs >= minSpeechMs && silentMs >= silenceMs) {
      if (recorder.state === 'recording') recorder.stop();
    }
  }, 200);

  const maxTimer = window.setTimeout(() => {
    if (recorder.state === 'recording') recorder.stop();
  }, maxMs);

  return {
    stop: () => {
      if (recorder.state === 'recording') recorder.stop();
    },
    cancel: () => {
      cancelled = true;
      if (recorder.state === 'recording') {
        recorder.onstop = null;
        recorder.stop();
      }
      cleanup();
    },
  };
}
