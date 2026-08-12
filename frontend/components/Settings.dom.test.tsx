// @vitest-environment jsdom

import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import Settings from './Settings';

let container: HTMLDivElement;
let root: Root;

const click = async (element: Element) => {
  await act(async () => {
    element.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
};

const getButton = (label: string) => Array.from(container.querySelectorAll('button')).find(
  (button) => button.textContent === label,
);

beforeEach(async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);

  await act(async () => {
    root.render(<Settings isOpen onClose={() => undefined} />);
  });
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
});

describe('Settings workspace copy and controls', () => {
  it('keeps all original language values while rendering Traditional Chinese labels', async () => {
    const languageSelect = container.querySelector<HTMLSelectElement>('select');
    expect(languageSelect).not.toBeNull();
    expect(languageSelect?.value).toBe('en');
    expect(Array.from(languageSelect?.options ?? []).map((option) => [option.value, option.textContent])).toEqual([
      ['en', '英文'],
      ['zh', '中文'],
      ['ja', '日文'],
      ['es', '西班牙文'],
      ['fr', '法文'],
    ]);

    const valueSetter = Object.getOwnPropertyDescriptor(
      window.HTMLSelectElement.prototype,
      'value',
    )?.set;
    valueSetter?.call(languageSelect, 'zh');
    await act(async () => {
      languageSelect?.dispatchEvent(new Event('change', { bubbles: true }));
    });

    expect(languageSelect?.value).toBe('zh');
  });

  it.each([
    ['API 金鑰', 'OpenAI 設定'],
    ['資料與儲存空間', '儲存空間'],
    ['通知', '通知偏好設定'],
    ['安全性', '隱私與安全性'],
    ['關於', '關於 OpenNotebookLM'],
  ])('renders %s tab content in Traditional Chinese after the tab is clicked', async (tab, content) => {
    const tabButton = getButton(tab);
    expect(tabButton).toBeDefined();
    await click(tabButton!);

    expect(container.textContent).toContain(content);
    expect(container.textContent).not.toContain('Notification Preferences');
  });
});
