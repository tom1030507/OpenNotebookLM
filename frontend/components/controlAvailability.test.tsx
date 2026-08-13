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

    const uploadButton = screen.getByRole('button', { name: '上傳來源' });
    const attachmentButton = screen.getByRole('button', { name: '附加檔案' });
    expect((uploadButton as HTMLButtonElement).disabled).toBe(true);
    expect((attachmentButton as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('請先選擇或建立專案後再新增來源')).not.toBeNull();

    fireEvent.click(uploadButton);
    fireEvent.click(attachmentButton);
    expect(requestedOpen).toBe(false);
  });

  it('marks notification and help as disabled, accessible coming-soon controls', () => {
    render(<ProjectDialogProvider><TopNav /></ProjectDialogProvider>);

    const notification = screen.getByRole('button', { name: '通知功能即將推出' });
    const help = screen.getByRole('button', { name: '說明功能即將推出' });
    expect((notification as HTMLButtonElement).disabled).toBe(true);
    expect((help as HTMLButtonElement).disabled).toBe(true);
  });
});
