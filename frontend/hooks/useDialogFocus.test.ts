// @vitest-environment jsdom

import { afterEach, describe, expect, it } from 'vitest';
import { getTabbableElements } from './useDialogFocus';

const renderDialog = (html: string) => {
  const dialog = window.document.createElement('div');
  dialog.innerHTML = html;
  window.document.body.appendChild(dialog);
  return dialog;
};

afterEach(() => {
  window.document.body.innerHTML = '';
});

describe('getTabbableElements', () => {
  it('includes embedded frames so modal content stays reachable by keyboard', () => {
    const dialog = renderDialog('<button>close</button><iframe title="preview"></iframe>');

    expect(getTabbableElements(dialog).map((element) => element.tagName)).toEqual([
      'BUTTON',
      'IFRAME',
    ]);
  });

  it('keeps only the checked radio of each group, matching native tab order', () => {
    const dialog = renderDialog(`
      <input type="radio" name="format" value="markdown" />
      <input type="radio" name="format" value="pdf" checked />
      <input type="radio" name="scope" value="all" />
      <input type="radio" name="scope" value="selection" />
    `);

    const values = getTabbableElements(dialog).map((element) => (element as HTMLInputElement).value);

    expect(values).toEqual(['pdf', 'all']);
  });

  it('excludes hidden inputs that can never receive focus', () => {
    const dialog = renderDialog('<input type="hidden" name="csrf" /><button>save</button>');

    expect(getTabbableElements(dialog).map((element) => element.tagName)).toEqual(['BUTTON']);
  });

  it('excludes disabled controls', () => {
    const dialog = renderDialog('<button disabled>saving</button><button>cancel</button>');

    expect(getTabbableElements(dialog).map((element) => element.textContent)).toEqual(['cancel']);
  });
});
