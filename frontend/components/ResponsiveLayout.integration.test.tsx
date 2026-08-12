// @vitest-environment jsdom

import React from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import ResponsiveLayout from './ResponsiveLayout';

afterEach(() => cleanup());

function renderWorkspace() {
  return render(
    <ResponsiveLayout
      sidebar={
        <section aria-label="來源內容">
          <button type="button">來源操作</button>
        </section>
      }
      conversationPanel={
        <section aria-label="對話內容">
          <button type="button">新增對話</button>
        </section>
      }
      rightPanel={
        <section aria-label="工作室內容">
          <button type="button">工作室操作</button>
        </section>
      }
    >
      <button type="button">聊天操作</button>
    </ResponsiveLayout>,
  );
}

describe('ResponsiveLayout component integration', () => {
  it('renders compact and desktop structures from stable CSS-controlled markup with an in-flow toolbar', () => {
    const { container } = renderWorkspace();
    const toolbar = screen.getByRole('navigation', { name: '工作區面板' });

    expect(toolbar.className).not.toContain('absolute');
    expect(toolbar.parentElement?.className).toContain('flex-col');
    expect(screen.getByRole('button', { name: '開啟來源面板' })).toBeTruthy();
    expect(container.querySelector('[data-workspace-region="sources"]')).toBeTruthy();
    expect(container.querySelector('[data-workspace-region="conversations"]')).toBeTruthy();
    expect(container.querySelector('[data-workspace-region="studio"]')).toBeTruthy();
  });

  it('opens a modal drawer with an in-flow close header, traps focus, restores it on every dismissal, and switches panels exclusively', () => {
    renderWorkspace();
    const sourcesTrigger = screen.getByRole('button', { name: '開啟來源面板' });
    const studioTrigger = screen.getByRole('button', { name: '開啟工作室面板' });

    fireEvent.click(sourcesTrigger);
    const sourcesDialog = screen.getByRole('dialog', { name: '來源面板' });
    const sourcesHeader = sourcesDialog.querySelector('header');
    const sourcesClose = within(sourcesDialog).getByRole('button', { name: '關閉來源面板' });

    expect(sourcesDialog.getAttribute('aria-modal')).toBe('true');
    expect(sourcesHeader).toBeTruthy();
    expect(sourcesHeader?.className).not.toContain('absolute');
    expect(document.activeElement).toBe(sourcesClose);

    fireEvent.keyDown(sourcesClose, { key: 'Tab', shiftKey: true });
    const sourcesAction = within(sourcesDialog).getByRole('button', { name: '來源操作' });
    expect(document.activeElement).toBe(sourcesAction);

    fireEvent.keyDown(sourcesAction, { key: 'Tab' });
    expect(document.activeElement).toBe(sourcesClose);

    fireEvent.click(studioTrigger);
    const studioDialog = screen.getByRole('dialog', { name: '工作室面板' });
    expect(screen.queryByRole('dialog', { name: '來源面板' })).toBeNull();
    fireEvent.click(within(studioDialog).getByRole('button', { name: '關閉工作室面板' }));
    expect(document.activeElement).toBe(studioTrigger);

    fireEvent.click(sourcesTrigger);
    fireEvent.keyDown(screen.getByRole('dialog', { name: '來源面板' }), { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(sourcesTrigger);

    fireEvent.click(sourcesTrigger);
    fireEvent.click(screen.getByRole('button', { name: '關閉面板' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(sourcesTrigger);
  });
});
