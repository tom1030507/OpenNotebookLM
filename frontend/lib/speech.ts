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

/** Speaks `text`, resolving when playback finishes and rejecting on failure. */
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
      reject(new Error(`Speech playback failed: ${event?.error ?? 'unknown error'}`));
    };

    speech.speak(utterance);
  });
}
