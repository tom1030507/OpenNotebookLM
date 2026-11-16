// @vitest-environment jsdom

import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Message } from '@/lib/api';
import CopyAnswerButton, { answerAsMarkdown } from './CopyAnswerButton';

const answer = {
  id: 'message-1',
  conversation_id: 'conversation-1',
  role: 'assistant',
  content: 'The outage lasted 14 hours [Source 1]. Repairs took a week [Source 2][Source 3].\n',
  created_at: '2026-11-16T00:00:00Z',
} as Message;

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('CopyAnswerButton (#241)', () => {
  it('writes the citation markers as the reader sees them', () => {
    expect(answerAsMarkdown(answer.content))
      .toBe('The outage lasted 14 hours [1]. Repairs took a week [2][3].');
  });

  it('copies the answer and says so', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { clipboard: { writeText } });
    render(<CopyAnswerButton message={answer} />);

    fireEvent.click(screen.getByRole('button', { name: 'Copy' }));

    expect(await screen.findByRole('button', { name: 'Copied' })).toBeTruthy();
    expect(writeText).toHaveBeenCalledWith('The outage lasted 14 hours [1]. Repairs took a week [2][3].');
  });

  it('says when the browser refuses the clipboard', async () => {
    vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } });
    render(<CopyAnswerButton message={answer} />);

    fireEvent.click(screen.getByRole('button', { name: 'Copy' }));

    expect(await screen.findByRole('button', { name: 'Could not copy' })).toBeTruthy();
  });
});
