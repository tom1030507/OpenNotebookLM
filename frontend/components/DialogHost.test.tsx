// @vitest-environment jsdom

import React from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import DialogHost from './DialogHost';
import { askText, confirmAction, useDialogRequests } from '@/lib/dialogs';

afterEach(() => {
  cleanup();
  useDialogRequests.setState({ active: null });
});

describe('DialogHost (#237)', () => {
  it('answers a confirmation with its button and closes', async () => {
    render(<DialogHost />);
    let answer: Promise<boolean> = Promise.resolve(false);
    act(() => {
      answer = confirmAction({ title: 'Move "Paper" to Trash?', confirmLabel: 'Move to Trash', danger: true });
    });

    const dialog = screen.getByRole('dialog', { name: 'Move "Paper" to Trash?' });
    expect(document.activeElement?.textContent).toBe('Cancel');
    fireEvent.click(screen.getByRole('button', { name: 'Move to Trash' }));

    await expect(answer).resolves.toBe(true);
    expect(dialog.isConnected).toBe(false);
  });

  it('treats Escape as cancel', async () => {
    render(<DialogHost />);
    let answer: Promise<boolean> = Promise.resolve(true);
    act(() => {
      answer = confirmAction({ title: 'Delete this conversation?', confirmLabel: 'Delete' });
    });

    fireEvent.keyDown(document, { key: 'Escape' });

    await expect(answer).resolves.toBe(false);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('asks for text prefilled with the current value and returns it trimmed', async () => {
    render(<DialogHost />);
    let answer: Promise<string | null> = Promise.resolve(null);
    act(() => {
      answer = askText({ title: 'Rename source', label: 'Source name', initialValue: 'Paper', confirmLabel: 'Rename' });
    });

    const input = screen.getByLabelText('Source name') as HTMLInputElement;
    expect(input.value).toBe('Paper');
    fireEvent.change(input, { target: { value: '   ' } });
    expect((screen.getByRole('button', { name: 'Rename' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(input, { target: { value: '  Annual report  ' } });
    fireEvent.submit(input.form!);

    await expect(answer).resolves.toBe('Annual report');
  });

  it('cancels a question that a newer one replaces', async () => {
    render(<DialogHost />);
    let first: Promise<boolean> = Promise.resolve(true);
    act(() => {
      first = confirmAction({ title: 'First?', confirmLabel: 'Yes' });
      void confirmAction({ title: 'Second?', confirmLabel: 'Yes' });
    });

    await expect(first).resolves.toBe(false);
    expect(screen.getByRole('dialog', { name: 'Second?' })).toBeTruthy();
  });
});
