import { describe, expect, it } from 'vitest';

import { getUploadFileError } from './uploadValidation';


describe('file upload validation', () => {
  it.each(['pdf', 'txt', 'md', 'docx', 'pptx', 'xlsx', 'epub'])(
    'accepts .%s files dropped onto the upload area',
    (extension) => {
      const file = new File(['source'], `notes.${extension}`);

      expect(getUploadFileError(file, 10, [])).toBeNull();
    },
  );

  it('rejects a file extension that the upload route does not support', () => {
    const file = new File(['binary'], 'program.exe');

    expect(getUploadFileError(file, 10, [])).toBe(
      'program.exe is not a supported file type',
    );
  });
});
