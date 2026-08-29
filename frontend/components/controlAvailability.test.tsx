// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import ChatArea from './chat/ChatArea';
import TopNav from './layout/TopNav';
import ProjectDialogProvider from './ProjectDialogProvider';
import useStore from '@/store/useStore';

// TopNav navigates on sign-out.
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: () => {} }),
}));



beforeEach(() => {
  HTMLElement.prototype.scrollIntoView = () => undefined;
  useStore.setState({
    currentProject: null,
    documents: [],
    messages: [],
  });
});

afterEach(() => {
  cleanup();
  useStore.getState().resetForTests();
});


describe('workspace control availability', () => {
  it('offers a working project action when source actions are unavailable', () => {
    const { container } = render(
      <ProjectDialogProvider>
        <ChatArea onAddSourcesOpenChange={() => undefined} />
      </ProjectDialogProvider>,
    );

    expect(screen.getByRole('heading', { name: 'Create a project to get started' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Upload sources' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Attach file' })).toBeNull();
    expect(screen.queryByText('Select or create a project before adding sources')).toBeNull();
    expect(
      container.querySelector('[data-layout="chat-composer"]')?.className.split(/\s+/),
    ).toContain('p-3');

    fireEvent.click(screen.getByRole('button', { name: 'New Project' }));
    expect(screen.getByRole('dialog', { name: 'Create New Project' })).toBeTruthy();
  });

  it('disables project creation outside the dialog provider', () => {
    render(<ChatArea onAddSourcesOpenChange={() => undefined} />);

    expect(
      (screen.getByRole('button', { name: 'New Project' }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it('exposes notifications and help as working controls', () => {
    render(<ProjectDialogProvider><TopNav /></ProjectDialogProvider>);

    const notification = screen.getByRole('button', { name: 'Notifications' });
    const help = screen.getByRole('button', { name: 'Help' });
    expect((notification as HTMLButtonElement).disabled).toBe(false);
    expect((help as HTMLButtonElement).disabled).toBe(false);
  });
});
