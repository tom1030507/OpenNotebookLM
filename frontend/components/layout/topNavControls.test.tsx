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

// jsdom has no layout, so a viewport width reaches the component the same way a
// browser reports it: through matchMedia.
const stubViewportWidth = (width: number) => {
  vi.stubGlobal('matchMedia', vi.fn((query: string) => {
    const maxWidth = /\(max-width:\s*([\d.]+)rem\)/.exec(query);

    return {
      media: query,
      matches: maxWidth ? width <= Number(maxWidth[1]) * 16 : false,
      addEventListener: () => {},
      removeEventListener: () => {},
    };
  }));
};

const renderTopNavAtWidth = (width: number) => {
  stubViewportWidth(width);
  return renderTopNav();
};

beforeEach(() => {
  push.mockClear();
  window.localStorage.clear();
  useStore.setState({ currentProject: project, projects: [project], documents: [] });
});

afterEach(() => {
  cleanup();
  useStore.setState(initialState, true);
  vi.unstubAllGlobals();
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

// 390px is the iPhone-class width where the full row of controls used to run off
// the side of the screen.
const PHONE_WIDTH = 390;
const DESKTOP_WIDTH = 1280;
const collapsedActions = ['New Project', 'Export', 'Toggle theme', 'Help', 'Settings'];

describe('TopNav at a phone-width viewport', () => {
  it('collapses the low-priority actions into a reachable overflow menu', () => {
    renderTopNavAtWidth(PHONE_WIDTH);

    // Only the badged control, the account menu and the overflow trigger keep a
    // slot on the bar; everything else moves into the menu.
    expect(screen.getByRole('button', { name: /^Notifications/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'User menu' })).toBeTruthy();
    collapsedActions.forEach((name) => {
      expect(screen.queryByRole('button', { name })).toBeNull();
    });

    fireEvent.click(screen.getByRole('button', { name: 'More actions' }));
    const menu = screen.getByRole('menu', { name: 'More actions' });

    collapsedActions.forEach((name) => {
      expect(within(menu).getByRole('button', { name })).toBeTruthy();
    });
  });

  it('runs a collapsed action and closes the menu behind it', () => {
    renderTopNavAtWidth(PHONE_WIDTH);

    fireEvent.click(screen.getByRole('button', { name: 'More actions' }));
    const menu = screen.getByRole('menu', { name: 'More actions' });
    fireEvent.click(within(menu).getByRole('button', { name: 'Settings' }));

    expect(screen.getByRole('dialog', { name: 'Settings' })).toBeTruthy();
    expect(screen.queryByRole('menu', { name: 'More actions' })).toBeNull();
  });

  it('gives every compact tap target a 44px box', () => {
    renderTopNavAtWidth(PHONE_WIDTH);

    [/^Notifications/, 'More actions', 'User menu'].forEach((name) => {
      const control = screen.getByRole('button', { name });
      expect(control.className).toContain('h-11');
      expect(control.className).toContain('w-11');
    });

    fireEvent.click(screen.getByRole('button', { name: 'More actions' }));
    const menu = screen.getByRole('menu', { name: 'More actions' });

    within(menu).getAllByRole('button').forEach((item) => {
      expect(item.className).toContain('min-h-11');
    });
  });

  it('closes the overflow menu on Escape and hands focus back to its trigger', () => {
    renderTopNavAtWidth(PHONE_WIDTH);

    const trigger = screen.getByRole('button', { name: 'More actions' });
    trigger.focus();
    fireEvent.click(trigger);

    const menu = screen.getByRole('menu', { name: 'More actions' });
    expect(trigger.getAttribute('aria-expanded')).toBe('true');
    expect(menu.contains(document.activeElement)).toBe(true);

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.queryByRole('menu', { name: 'More actions' })).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it('opens only one top-bar menu at a time so no action is offered twice', () => {
    renderTopNavAtWidth(PHONE_WIDTH);

    fireEvent.click(screen.getByRole('button', { name: 'More actions' }));
    fireEvent.click(screen.getByRole('button', { name: 'User menu' }));

    expect(screen.queryByRole('menu', { name: 'More actions' })).toBeNull();
    expect(screen.getAllByRole('button', { name: 'Settings' })).toHaveLength(1);
  });

  it('lets the project name truncate instead of pushing the controls off screen', () => {
    renderTopNavAtWidth(PHONE_WIDTH);

    const title = screen.getByRole('heading', { level: 1 });

    expect(title.className).toContain('truncate');
    expect(title.parentElement?.className).toContain('min-w-0');
  });

  it('keeps the full row of controls at desktop width', () => {
    renderTopNavAtWidth(DESKTOP_WIDTH);

    collapsedActions.forEach((name) => {
      expect(screen.getByRole('button', { name })).toBeTruthy();
    });
    expect(screen.queryByRole('button', { name: 'More actions' })).toBeNull();
  });

  it('keeps the full row of controls when the environment cannot report a width', () => {
    vi.stubGlobal('matchMedia', undefined);
    renderTopNav();

    collapsedActions.forEach((name) => {
      expect(screen.getByRole('button', { name })).toBeTruthy();
    });
    expect(screen.queryByRole('button', { name: 'More actions' })).toBeNull();
  });
});
