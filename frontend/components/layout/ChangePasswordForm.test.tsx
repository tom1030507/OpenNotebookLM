// @vitest-environment jsdom

import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import api, { ApiError } from '@/lib/api';
import ChangePasswordForm from './ChangePasswordForm';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const fill = (current: string, next: string, confirmation: string) => {
  fireEvent.change(screen.getByLabelText('Current password'), { target: { value: current } });
  fireEvent.change(screen.getByLabelText('New password'), { target: { value: next } });
  fireEvent.change(screen.getByLabelText('Confirm new password'), { target: { value: confirmation } });
  fireEvent.click(screen.getByRole('button', { name: 'Change password' }));
};

describe('ChangePasswordForm (#248)', () => {
  it('changes the password and clears the fields', async () => {
    const change = vi.spyOn(api, 'changePassword').mockResolvedValue(undefined);
    render(<ChangePasswordForm />);

    fill('old-password', 'new-password-1', 'new-password-1');

    expect(await screen.findByRole('status')).toHaveProperty('textContent', 'Password changed.');
    expect(change).toHaveBeenCalledWith('old-password', 'new-password-1');
    expect(screen.getByLabelText('Current password')).toHaveProperty('value', '');
  });

  it('stops a mismatched confirmation before asking the server', () => {
    const change = vi.spyOn(api, 'changePassword');
    render(<ChangePasswordForm />);

    fill('old-password', 'new-password-1', 'new-password-2');

    expect(screen.getByRole('alert').textContent).toBe('The new passwords do not match.');
    expect(change).not.toHaveBeenCalled();
  });

  it('shows the server reason, such as a wrong current password', async () => {
    vi.spyOn(api, 'changePassword').mockRejectedValue(
      new ApiError(400, 'The current password is incorrect.'),
    );
    render(<ChangePasswordForm />);

    fill('wrong-password', 'new-password-1', 'new-password-1');

    expect((await screen.findByRole('alert')).textContent).toBe('The current password is incorrect.');
    expect(screen.getByLabelText('Current password')).toHaveProperty('value', 'wrong-password');
  });
});
