// @vitest-environment jsdom

import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import FileUpload from './FileUpload';


const jsonResponse = (body: unknown): Response => new Response(JSON.stringify(body), {
  status: 200,
  headers: { 'Content-Type': 'application/json' },
});


afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});


describe('FileUpload', () => {
  it('uses the backend formats and size in the file picker', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      allowed_file_types: ['pdf', 'md'],
      max_file_size_mb: 23,
    })));
    const { container } = render(<FileUpload onUpload={async () => undefined} />);

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    expect(await screen.findByText('Supported file types: .pdf, .md · Maximum file size: 23MB'))
      .toBeTruthy();
    expect(fileInput.accept).toBe('.pdf,.md');

    fireEvent.change(fileInput, {
      target: { files: [new File(['word'], 'report.docx')] },
    });
    expect(await screen.findByText('report.docx is not a supported file type')).toBeTruthy();
  });

  it('shows the server detail when a file upload fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      allowed_file_types: ['pdf'],
      max_file_size_mb: 23,
    })));
    const detail = 'File type is not supported. Allowed types: md, pdf, txt';
    const onUpload = vi.fn().mockRejectedValue(new Error(detail));
    const { container } = render(<FileUpload onUpload={onUpload} />);
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;

    await screen.findByText('Supported file types: .pdf · Maximum file size: 23MB');
    fireEvent.change(fileInput, {
      target: { files: [new File(['pdf'], 'paper.pdf', { type: 'application/pdf' })] },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Upload 1 file(s)' }));

    expect(await screen.findByText(detail)).toBeTruthy();
  });
});
