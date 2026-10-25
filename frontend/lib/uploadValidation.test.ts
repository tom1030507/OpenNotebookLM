import { describe, expect, it } from 'vitest';

import { getUploadFileError } from './uploadValidation';


const allowedFileTypes = [
  'pdf', 'txt', 'md', 'docx', 'pptx', 'xlsx', 'epub',
  'png', 'jpg', 'jpeg', 'webp',
  'mp3', 'm4a', 'wav', 'ogg', 'webm', 'flac',
];


describe('file upload validation', () => {
  it.each([
    'pdf', 'txt', 'md', 'docx', 'pptx', 'xlsx', 'epub',
    'png', 'jpg', 'jpeg', 'webp',
    'mp3', 'm4a', 'wav', 'ogg', 'webm', 'flac',
  ])(
    'accepts .%s files dropped onto the upload area',
    (extension) => {
      const file = new File(['source'], `notes.${extension}`);

      expect(getUploadFileError(file, 50, [], allowedFileTypes)).toBeNull();
    },
  );

  it('rejects file types omitted by the backend runtime configuration', () => {
    const file = new File(['word'], 'report.docx');

    expect(getUploadFileError(file, 50, [], ['pdf', 'md'])).toBe(
      'report.docx is not a supported file type',
    );
  });

  it('rejects a file extension that the upload route does not support', () => {
    const file = new File(['binary'], 'program.exe');

    expect(getUploadFileError(file, 50, [], allowedFileTypes)).toBe(
      'program.exe is not a supported file type',
    );
  });

  it('uses the configured size limit', () => {
    const file = new File([new Uint8Array(1024 * 1024 + 1)], 'notes.txt');

    expect(getUploadFileError(file, 1, [], ['txt'])).toBe(
      'notes.txt exceeds 1MB limit',
    );
  });
});
