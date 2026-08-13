/**
 * Speech playback for Studio's audio summary.
 *
 * The summary itself comes from the backend as Markdown; the audio is produced
 * in the browser with the Web Speech API, so no synthesis service is required.
 */

/** Strips the Markdown that would otherwise be read out as punctuation. */
export function summaryToSpeech(markdown: string): string {
  const spoken = markdown
    // fenced code blocks carry nothing worth hearing
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]*)`/g, '$1')
    // links and images: keep the label, drop the target
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    // headings, emphasis, quotes and list markers
    .replace(/^\s{0,3}#{1,6}\s*/gm, '')
    .replace(/^\s{0,3}>\s?/gm, '')
    .replace(/^\s*[-*+]\s+/gm, '')
    .replace(/(\*\*|__)(.*?)\1/g, '$2')
    .replace(/(\*|_)(.*?)\1/g, '$2')
    // horizontal rules and leftover table pipes
    .replace(/^\s*([-*_]\s*){3,}$/gm, '')
    .replace(/\|/g, ' ')
    // bare URLs read terribly
    .replace(/https?:\/\/\S+/g, '')
    .replace(/[ \t]+/g, ' ')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .join('\n');

  return spoken.trim();
}

function synthesis(): SpeechSynthesis | null {
  if (typeof window === 'undefined') return null;
  const candidate = (window as unknown as { speechSynthesis?: SpeechSynthesis }).speechSynthesis;
  return candidate && typeof candidate.speak === 'function' ? candidate : null;
}

export function isSpeechSupported(): boolean {
  return synthesis() !== null;
}

export function stopSpeaking(): void {
  synthesis()?.cancel();
}

/**
 * Error values a browser reports when playback was cancelled rather than
 * broken: `cancel()` fires `onerror` on whatever was being spoken. Chrome says
 * 'interrupted' for a reading already under way and 'canceled' for one still
 * queued; the British spelling is accepted for engines that prefer it.
 */
const STOP_ERRORS = new Set(['interrupted', 'canceled', 'cancelled']);

/**
 * Speaks `text`, resolving when playback finishes or is stopped, and rejecting
 * only when synthesis itself fails.
 */
export function speakText(text: string, rate = 1): Promise<void> {
  const speech = synthesis();

  if (!speech) {
    return Promise.reject(new Error('Speech playback is not available in this browser.'));
  }

  const spoken = text.trim();
  if (!spoken) {
    return Promise.reject(new Error('There is nothing to read out.'));
  }

  return new Promise<void>((resolve, reject) => {
    // Cancel first: replaying while speaking otherwise queues a second reading.
    speech.cancel();

    const utterance = new SpeechSynthesisUtterance(spoken);
    utterance.rate = rate;
    utterance.onend = () => resolve();
    utterance.onerror = (event: { error?: string }) => {
      const error = event?.error ?? 'unknown error';

      // Stopping playback — either through stopSpeaking() or the cancel above —
      // is reported as an error too. A deliberate stop is not a fault, so the
      // reading just ends; only real synthesis trouble reaches the caller.
      if (STOP_ERRORS.has(error)) {
        resolve();
        return;
      }

      reject(new Error(`Speech playback failed: ${error}`));
    };

    speech.speak(utterance);
  });
}
