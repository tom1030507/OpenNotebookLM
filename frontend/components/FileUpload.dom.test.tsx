// @vitest-environment jsdom

import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import FileUpload from './FileUpload';

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
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
  vi.restoreAllMocks();
});

describe('FileUpload URL validation', () => {
  it('shows the Traditional Chinese validation message after an invalid URL is submitted', async () => {
    const onUpload = vi.fn().mockResolvedValue(undefined);

    await act(async () => {
      root.render(<FileUpload onUpload={onUpload} />);
    });

    const urlTab = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent === 'URL',
    );
    expect(urlTab).toBeDefined();
    await click(urlTab!);

    const input = container.querySelector<HTMLInputElement>(
      'input[placeholder="輸入網站 URL..."]',
    );
    expect(input).not.toBeNull();

    const inputValueSetter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      'value',
    )?.set;
    inputValueSetter?.call(input, 'not-a-url');
    await act(async () => {
      input?.dispatchEvent(new Event('input', { bubbles: true }));
    });

    const addButton = Array.from(container.querySelectorAll('button')).find(
      (button) => button.textContent === '新增',
    );
    expect(addButton).toBeDefined();
    await click(addButton!);

    expect(container.textContent).toContain('請輸入有效的 URL');
    expect(container.textContent).not.toContain('Please enter a valid URL');
    expect(onUpload).not.toHaveBeenCalled();
  });
});
