import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';

const { PDFDocument } = createRequire(import.meta.url)('pdf-lib') as typeof import('pdf-lib');

import { test, expect } from '../support/fixtures.js';
import { generatePdf } from '../support/pdf.js';

test('generates a valid searchable PDF inside the test output', async ({}, testInfo) => {
  const outputPath = testInfo.outputPath('generated-observatory.pdf');
  await generatePdf(outputPath, 'Observatory Field Notes', 'The access code is ORBIT-7319.');

  const bytes = await readFile(outputPath);
  const document = await PDFDocument.load(bytes);
  expect(document.getPageCount()).toBe(1);
  expect(bytes.subarray(0, 4).toString('ascii')).toBe('%PDF');
});
