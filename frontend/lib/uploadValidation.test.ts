import { describe, expect, it } from 'vitest';

import { getUploadFileError } from './uploadValidation';


describe('file upload validation', () => {
  it('rejects a non-PDF file dropped onto the upload area', () => {
    const file = new File(['notes'], 'notes.txt', { type: 'text/plain' });

    expect(getUploadFileError(file, 10, [])).toBe(
      'notes.txt 不是支援的 PDF 檔案',
    );
  });
});
