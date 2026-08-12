// @vitest-environment jsdom

import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import TopNav from './TopNav';

let container: HTMLDivElement;
let root: Root;

const click = async (element: Element) => {
  await act(async () => {
    element.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
};

beforeEach(async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);

  await act(async () => {
    root.render(<TopNav />);
  });
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
});

describe('TopNav user menu', () => {
  it('opens Settings and closes the user menu when its Settings action is clicked', async () => {
    const userButton = Array.from(container.querySelectorAll('button')).find(
      (button) => button.querySelector('.lucide-user'),
    );
    expect(userButton).toBeDefined();
    await click(userButton!);
    expect(container.textContent).toContain('個人資料');

    const settingsAction = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent === '設定',
    );
    expect(settingsAction).toBeDefined();
    await click(settingsAction!);

    expect(container.textContent).not.toContain('個人資料');
    expect(container.querySelector('h2')?.textContent).toBe('設定');
  });
});
