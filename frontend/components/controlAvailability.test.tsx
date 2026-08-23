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
  it('disables source entry points and does not request the dialog without a project', () => {
    let requestedOpen = false;
    render(<ChatArea onAddSourcesOpenChange={(isOpen) => { requestedOpen = isOpen; }} />);

    const uploadButton = screen.getByRole('button', { name: 'Upload sources' });
    const attachmentButton = screen.getByRole('button', { name: 'Attach file' });
    expect((uploadButton as HTMLButtonElement).disabled).toBe(true);
    expect((attachmentButton as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('Select or create a project before adding sources')).not.toBeNull();

    fireEvent.click(uploadButton);
    fireEvent.click(attachmentButton);
    expect(requestedOpen).toBe(false);
  });

  it('exposes notifications and help as working controls', () => {
    render(<ProjectDialogProvider><TopNav /></ProjectDialogProvider>);

    const notification = screen.getByRole('button', { name: 'Notifications' });
    const help = screen.getByRole('button', { name: 'Help' });
    expect((notification as HTMLButtonElement).disabled).toBe(false);
    expect((help as HTMLButtonElement).disabled).toBe(false);
  });
});
