import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const css = readFileSync(fileURLToPath(new URL('./globals.css', import.meta.url)), 'utf8');

interface StyleRule {
  selector: string;
  layered: boolean;
}

/**
 * Walks the stylesheet and records each style rule together with whether it sits
 * inside a cascade layer. Tailwind v4 emits every utility inside
 * `@layer utilities`, and unlayered rules outrank every layer regardless of
 * specificity, so an unlayered global reset silently defeats utility classes.
 */
function styleRules(source: string): StyleRule[] {
  const rules: StyleRule[] = [];
  const openBlocks: boolean[] = [];
  let prelude = '';

  for (const char of source.replace(/\/\*[\s\S]*?\*\//g, '')) {
    if (char === '{') {
      const head = prelude.trim();
      const isLayer = /^@layer\b/.test(head);

      if (!head.startsWith('@')) {
        rules.push({ selector: head, layered: openBlocks.some(Boolean) });
      }

      openBlocks.push(isLayer);
      prelude = '';
    } else if (char === '}') {
      openBlocks.pop();
      prelude = '';
    } else {
      prelude += char;
    }
  }

  return rules;
}

const universalRules = () => styleRules(css).filter((rule) => (
  rule.selector.split(',').some((part) => part.trim() === '*')
));

describe('globals.css cascade layers', () => {
  it('still applies a global reset through the universal selector', () => {
    expect(universalRules().length).toBeGreaterThan(0);
    expect(css).toMatch(/box-sizing:\s*border-box/);
  });

  it('keeps every universal reset inside a cascade layer so Tailwind utilities win', () => {
    expect(universalRules().filter((rule) => !rule.layered)).toEqual([]);
  });
});
