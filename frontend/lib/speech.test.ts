// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest';
import { isSpeechSupported, speakText, stopSpeaking, summaryToSpeech } from './speech';

interface FakeUtterance {
  text: string;
  rate: number;
  onend?: () => void;
  onerror?: (event: { error: string }) => void;
}

function installSpeechSynthesis() {
  const spoken: FakeUtterance[] = [];
  let cancelled = 0;

  class Utterance {
    text: string;
    rate = 1;
    onend?: () => void;
    onerror?: (event: { error: string }) => void;

    constructor(text: string) {
      this.text = text;
    }
  }

  vi.stubGlobal('SpeechSynthesisUtterance', Utterance);
  vi.stubGlobal('speechSynthesis', {
    speak: (u: FakeUtterance) => spoken.push(u),
    cancel: () => { cancelled += 1; },
    speaking: false,
  });

  return { spoken, cancelled: () => cancelled };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('summaryToSpeech', () => {
  it('strips Markdown so headings and emphasis are not read out as symbols', () => {
    const markdown = [
      '# Project summary',
      '',
      '## Sources',
      '- **Example Domain** — a `test` page',
      '',
      'See [the docs](https://example.com) for more.',
    ].join('\n');

    const spoken = summaryToSpeech(markdown);

    expect(spoken).not.toMatch(/[#*`\[\]()]/);
    expect(spoken).toContain('Project summary');
    expect(spoken).toContain('Example Domain');
    expect(spoken).toContain('the docs');
    expect(spoken).not.toContain('https://example.com');
  });

  it('collapses blank runs so playback does not stall on whitespace', () => {
    expect(summaryToSpeech('a\n\n\n\nb')).toBe('a\nb');
  });

  it('returns an empty string for content with nothing to say', () => {
    expect(summaryToSpeech('   \n\n  ')).toBe('');
  });
});

describe('isSpeechSupported', () => {
  it('is false when the browser has no speech synthesis', () => {
    vi.stubGlobal('speechSynthesis', undefined);
    expect(isSpeechSupported()).toBe(false);
  });

  it('is true once speech synthesis is present', () => {
    installSpeechSynthesis();
    expect(isSpeechSupported()).toBe(true);
  });
});

describe('speakText', () => {
  it('cancels any current speech before starting, so replays do not overlap', async () => {
    const fake = installSpeechSynthesis();

    const finished = speakText('hello');
    expect(fake.cancelled()).toBe(1);
    expect(fake.spoken).toHaveLength(1);
    expect(fake.spoken[0].text).toBe('hello');

    fake.spoken[0].onend?.();
    await expect(finished).resolves.toBeUndefined();
  });

  it('rejects when the utterance fails', async () => {
    const fake = installSpeechSynthesis();

    const finished = speakText('hello');
    fake.spoken[0].onerror?.({ error: 'synthesis-failed' });

    await expect(finished).rejects.toThrow(/synthesis-failed/);
  });

  it.each(['interrupted', 'canceled', 'cancelled'])(
    'settles quietly when playback is stopped (%s)',
    async (error) => {
      const fake = installSpeechSynthesis();

      const finished = speakText('hello');
      stopSpeaking();
      // cancel() makes the browser report the stop as an error on the utterance.
      fake.spoken[0].onerror?.({ error });

      await expect(finished).resolves.toBeUndefined();
    },
  );

  it('ignores a late error once playback has finished', async () => {
    const fake = installSpeechSynthesis();

    const finished = speakText('hello');
    fake.spoken[0].onend?.();
    fake.spoken[0].onerror?.({ error: 'synthesis-failed' });

    await expect(finished).resolves.toBeUndefined();
  });

  it('keeps a replay clean when cancelling the previous reading errors', async () => {
    const fake = installSpeechSynthesis();

    const first = speakText('hello');
    // Replaying cancels the first utterance, which reports 'interrupted'.
    const second = speakText('again');
    fake.spoken[0].onerror?.({ error: 'interrupted' });

    await expect(first).resolves.toBeUndefined();

    fake.spoken[1].onend?.();
    await expect(second).resolves.toBeUndefined();
  });

  it('rejects immediately when speech is unavailable', async () => {
    vi.stubGlobal('speechSynthesis', undefined);
    await expect(speakText('hello')).rejects.toThrow(/not available/i);
  });

  it('refuses to speak nothing', async () => {
    installSpeechSynthesis();
    await expect(speakText('   ')).rejects.toThrow(/nothing/i);
  });
});

describe('stopSpeaking', () => {
  it('cancels playback and tolerates an unsupported browser', () => {
    const fake = installSpeechSynthesis();
    stopSpeaking();
    expect(fake.cancelled()).toBe(1);

    vi.stubGlobal('speechSynthesis', undefined);
    expect(() => stopSpeaking()).not.toThrow();
  });
});
