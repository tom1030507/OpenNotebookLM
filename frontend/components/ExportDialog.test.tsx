// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import api from '@/lib/api';
import ExportDialog from './ExportDialog';

const downloads: string[] = [];

beforeEach(() => {
  downloads.length = 0;
  class TestURL extends URL {
    static createObjectURL = vi.fn(() => 'blob:export');
    static revokeObjectURL = vi.fn();
  }
  vi.stubGlobal('URL', TestURL);
  vi.spyOn(api, 'exportConversation').mockResolvedValue(new Blob(['# Export']));
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function click(
    this: HTMLAnchorElement,
  ) {
    downloads.push(this.download);
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('ExportDialog', () => {
  it('keeps Unicode in filenames and maps Markdown to .md', async () => {
    render(
      <ExportDialog
        type="conversation"
        id="conversation-1"
        name={'光反應會產生什麼？/ draft\u0007'}
        onClose={() => undefined}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Export' }));

    await waitFor(() => expect(downloads).toEqual(['光反應會產生什麼？_ draft_.md']));
  });

  it('keeps the selected extension for JSON exports', async () => {
    render(
      <ExportDialog
        type="conversation"
        id="conversation-1"
        name="Research notes"
        onClose={() => undefined}
      />,
    );

    fireEvent.click(screen.getByRole('radio', { name: /JSON/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Export' }));

    await waitFor(() => expect(downloads).toEqual(['Research notes.json']));
    expect(api.exportConversation).toHaveBeenCalledWith('conversation-1', 'json');
  });
});
