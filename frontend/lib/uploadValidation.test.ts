import { describe, expect, it, vi } from 'vitest';

import { getTextContentError, getUploadFileError } from './uploadValidation';


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
    async (extension) => {
      const file = new File(['source'], `notes.${extension}`);

      expect(await getUploadFileError(file, 50, [], allowedFileTypes, 100)).toBeNull();
    },
  );

  it('rejects file types omitted by the backend runtime configuration', async () => {
    const file = new File(['word'], 'report.docx');

    expect(await getUploadFileError(file, 50, [], ['pdf', 'md'], 100)).toBe(
      'report.docx is not a supported file type',
    );
  });

  it('rejects a file extension that the upload route does not support', async () => {
    const file = new File(['binary'], 'program.exe');

    expect(await getUploadFileError(file, 50, [], allowedFileTypes, 100)).toBe(
      'program.exe is not a supported file type',
    );
  });

  it('uses the configured size limit', async () => {
    const file = new File([new Uint8Array(1024 * 1024 + 1)], 'notes.txt');

    expect(await getUploadFileError(file, 1, [], ['txt'], 100)).toBe(
      'notes.txt exceeds 1MB limit',
    );
  });

  it('rejects text that exceeds the chunk budget by Unicode character count', async () => {
    const file = new File(['a😀a'], 'notes.txt');
    Object.defineProperty(file, 'text', { value: async () => 'a😀a' });

    await expect(getUploadFileError(file, 50, [], ['txt'], 2)).resolves.toBe(
      'notes.txt: Text exceeds about 2 characters. Split it into smaller sources '
      + 'or ask your administrator to raise the per-source chunk limit.',
    );
  });

  it('rejects very large text files without reading the whole file', async () => {
    const file = new File([new Uint8Array(81)], 'notes.md');
    const readText = vi.fn(async () => '');
    Object.defineProperty(file, 'text', { value: readText });

    await expect(getUploadFileError(file, 50, [], ['md'], 20)).resolves.toContain(
      'Text exceeds about 20 characters',
    );
    expect(readText).not.toHaveBeenCalled();
  });

  it('does not apply the text budget to binary sources', async () => {
    const file = new File(['binary'], 'scan.pdf');

    expect(await getUploadFileError(file, 50, [], ['pdf'], 1)).toBeNull();
  });

  it('counts pasted text by Unicode code point', () => {
    expect(getTextContentError('😀😀😀', 2)).toBe(
      'Text exceeds about 2 characters. Split it into smaller sources or ask your '
      + 'administrator to raise the per-source chunk limit.',
    );
  });
});
