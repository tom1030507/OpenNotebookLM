// @vitest-environment jsdom

import React from 'react';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import TopNav from './TopNav';
import ProjectDialogProvider from '../ProjectDialogProvider';
import useStore from '@/store/useStore';
import type { Document, Project } from '@/lib/api';

const push = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
}));

const project: Project = {
  id: 'project-1',
  name: 'Research notes',
  description: null,
  meta_json: {},
  created_at: '2026-08-13T00:00:00Z',
  updated_at: '2026-08-13T00:00:00Z',
  document_count: 1,
  conversation_count: 0,
};

const processing: Document = {
  id: 'document-1',
  name: 'Working paper',
  type: 'pdf',
  content: '',
  meta: {},
  status: 'processing',
  created_at: '2026-08-13T00:00:00Z',
  updated_at: '2026-08-13T00:00:00Z',
  chunk_count: 0,
};

const initialState = useStore.getState();
const renderTopNav = () => render(
  <ProjectDialogProvider>
    <TopNav />
  </ProjectDialogProvider>,
);

beforeEach(() => {
  push.mockClear();
  window.localStorage.clear();
  useStore.setState({ currentProject: project, projects: [project], documents: [] });
});

afterEach(() => {
  cleanup();
  useStore.setState(initialState, true);
});

describe('TopNav controls that were previously inert', () => {
  it('signs the user out by clearing credentials and returning to the login page', () => {
    window.localStorage.setItem('access_token', 'demo');
    window.localStorage.setItem('auth_token', 'demo');
    window.localStorage.setItem('user', JSON.stringify({ username: 'demo', email: 'demo@example.com' }));
    renderTopNav();

    fireEvent.click(screen.getByRole('button', { name: 'User menu' }));
    const signOut = screen.getByRole('button', { name: 'Sign out' });
    expect((signOut as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(signOut);

    expect(window.localStorage.getItem('access_token')).toBeNull();
    expect(window.localStorage.getItem('auth_token')).toBeNull();
    expect(window.localStorage.getItem('user')).toBeNull();
    expect(push).toHaveBeenCalledWith('/login');
  });

  it('shows the signed-in account in the profile dialog', () => {
    window.localStorage.setItem('user', JSON.stringify({ username: 'ada', email: 'ada@example.com' }));
    renderTopNav();

    fireEvent.click(screen.getByRole('button', { name: 'User menu' }));
    fireEvent.click(screen.getByRole('button', { name: 'Profile' }));

    const dialog = screen.getByRole('dialog', { name: 'Profile' });
    expect(within(dialog).getByText('ada')).toBeTruthy();
    expect(within(dialog).getByText('ada@example.com')).toBeTruthy();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'Profile' })).toBeNull();
  });

  it('opens a help dialog with getting-started guidance', () => {
    renderTopNav();

    const help = screen.getByRole('button', { name: 'Help' });
    expect((help as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(help);

    const dialog = screen.getByRole('dialog', { name: 'Help' });
    expect(within(dialog).getByText(/Create a project/i)).toBeTruthy();
    expect(within(dialog).getByRole('link', { name: /GitHub/i })).toBeTruthy();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'Help' })).toBeNull();
  });

  it('reports document processing state through notifications', () => {
    useStore.setState({ documents: [processing] });
    renderTopNav();

    const bell = screen.getByRole('button', { name: /^Notifications/ });
    expect((bell as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(bell);

    const dialog = screen.getByRole('dialog', { name: 'Notifications' });
    expect(within(dialog).getByText('Working paper')).toBeTruthy();
    expect(within(dialog).getByText(/processing/i)).toBeTruthy();
  });

  it('says so when there is nothing to notify about', () => {
    renderTopNav();

    fireEvent.click(screen.getByRole('button', { name: /^Notifications/ }));

    const dialog = screen.getByRole('dialog', { name: 'Notifications' });
    expect(within(dialog).getByText(/No notifications/i)).toBeTruthy();
  });
});
