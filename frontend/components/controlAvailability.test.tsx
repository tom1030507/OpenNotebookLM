// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import ChatArea from './chat/ChatArea';
import TopNav from './layout/TopNav';
import ProjectDialogProvider from './ProjectDialogProvider';
import useStore from '@/store/useStore';


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
  useStore.setState(useStore.getInitialState(), true);
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

  it('marks notification and help as disabled, accessible coming-soon controls', () => {
    render(<ProjectDialogProvider><TopNav /></ProjectDialogProvider>);

    const notification = screen.getByRole('button', { name: 'Notifications (coming soon)' });
    const help = screen.getByRole('button', { name: 'Help (coming soon)' });
    expect((notification as HTMLButtonElement).disabled).toBe(true);
    expect((help as HTMLButtonElement).disabled).toBe(true);
  });
});
