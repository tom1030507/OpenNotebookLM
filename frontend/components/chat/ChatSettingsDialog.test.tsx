// @vitest-environment jsdom

import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const apiMock = vi.hoisted(() => ({
  getChatSettings: vi.fn(),
  updateChatSettings: vi.fn(),
}));

vi.mock('@/lib/api', () => ({ default: apiMock }));

import ChatSettingsDialog from './ChatSettingsDialog';

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe('chat settings dialog', () => {
  it('loads the project settings and saves the edited ones', async () => {
    apiMock.getChatSettings.mockResolvedValue({
      role: 'default', instructions: '', answer_length: 'default', output_language: 'auto',
    });
    apiMock.updateChatSettings.mockResolvedValue({});
    const onClose = vi.fn();
    const onOutputLanguageChanged = vi.fn();
    const user = userEvent.setup();

    render(
      <ChatSettingsDialog
        projectId="p1"
        onClose={onClose}
        onOutputLanguageChanged={onOutputLanguageChanged}
      />,
    );

    expect(screen.queryByLabelText('Custom instructions')).toBeNull();
    await user.click(await screen.findByRole('radio', { name: /Custom/ }));
    await user.type(screen.getByLabelText('Custom instructions'), 'Be terse.');
    await user.click(screen.getByRole('radio', { name: 'Shorter' }));
    await user.selectOptions(screen.getByLabelText('Output language'), 'zh-Hant');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(apiMock.getChatSettings).toHaveBeenCalledWith('p1');
    expect(apiMock.updateChatSettings).toHaveBeenCalledWith('p1', {
      role: 'custom', instructions: 'Be terse.', answer_length: 'shorter',
      output_language: 'zh-Hant',
    });
    expect(onOutputLanguageChanged).toHaveBeenCalledOnce();
  });

  it('keeps the dialog open and says so when saving fails', async () => {
    apiMock.getChatSettings.mockResolvedValue({
      role: 'learning_guide', instructions: '', answer_length: 'longer', output_language: 'auto',
    });
    apiMock.updateChatSettings.mockRejectedValue(new Error('offline'));
    const onClose = vi.fn();
    const user = userEvent.setup();

    render(<ChatSettingsDialog projectId="p1" onClose={onClose} />);
    await screen.findByRole('radio', { name: /Learning guide/ });
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
  });
});
