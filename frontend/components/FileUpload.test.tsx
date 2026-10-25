// @vitest-environment jsdom

import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
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
      max_text_characters: 462000,
    })));
    const { container } = render(<FileUpload onUpload={async () => undefined} />);

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    expect(await screen.findByText(
      'Supported file types: .pdf, .md · Maximum file size: 23MB · Plain text sources: about 462,000 characters per source',
    )).toBeTruthy();
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
      max_text_characters: 462000,
    })));
    const detail = 'File type is not supported. Allowed types: md, pdf, txt';
    const onUpload = vi.fn().mockRejectedValue(new Error(detail));
    const { container } = render(<FileUpload onUpload={onUpload} />);
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;

    await screen.findByText(
      'Supported file types: .pdf · Maximum file size: 23MB · Plain text sources: about 462,000 characters per source',
    );
    fireEvent.change(fileInput, {
      target: { files: [new File(['pdf'], 'paper.pdf', { type: 'application/pdf' })] },
    });
    await screen.findByText('Selected Files:');
    fireEvent.click(screen.getByRole('button', { name: 'Upload 1 file(s)' }));

    expect(await screen.findByText(detail)).toBeTruthy();
  });

  it('blocks plain text beyond the backend chunk budget before upload', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      allowed_file_types: ['txt'],
      max_file_size_mb: 23,
      max_text_characters: 2,
    })));
    const onUpload = vi.fn();
    const { container } = render(<FileUpload onUpload={onUpload} />);
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['a😀a'], 'notes.txt');
    Object.defineProperty(file, 'text', { value: async () => 'a😀a' });

    await screen.findByText(
      'Supported file types: .txt · Maximum file size: 23MB · Plain text sources: about 2 characters per source',
    );
    fireEvent.change(fileInput, { target: { files: [file] } });

    expect(await screen.findByText(
      'notes.txt: Text exceeds about 2 characters. Split it into smaller sources or ask your administrator to raise the per-source chunk limit.',
    )).toBeTruthy();
    expect(screen.queryByText('Selected Files:')).toBeNull();
    expect(onUpload).not.toHaveBeenCalled();
  });

  it('blocks pasted text beyond the backend chunk budget', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      allowed_file_types: ['txt'],
      max_file_size_mb: 23,
      max_text_characters: 2,
    })));
    const onAddText = vi.fn();
    const { container } = render(
      <FileUpload onUpload={async () => undefined} onAddText={onAddText} />,
    );

    await waitFor(() => {
      expect((container.querySelector('input[type="file"]') as HTMLInputElement).disabled)
        .toBe(false);
    });
    fireEvent.click(screen.getByRole('button', { name: 'Text' }));
    fireEvent.change(screen.getByLabelText('Source title'), { target: { value: 'Notes' } });
    fireEvent.change(screen.getByLabelText('Source text'), { target: { value: '😀😀😀' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add text' }));

    expect(await screen.findByText(
      'Text exceeds about 2 characters. Split it into smaller sources or ask your administrator to raise the per-source chunk limit.',
    )).toBeTruthy();
    expect(onAddText).not.toHaveBeenCalled();
  });

  it('does not restore a removed file after text validation finishes', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      allowed_file_types: ['pdf', 'txt'],
      max_file_size_mb: 23,
      max_text_characters: 100,
    })));
    const onUpload = vi.fn(async () => undefined);
    const { container } = render(<FileUpload onUpload={onUpload} multiple />);
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    await screen.findByText(
      'Supported file types: .pdf, .txt · Maximum file size: 23MB · Plain text sources: about 100 characters per source',
    );

    const existingFile = new File(['pdf'], 'existing.pdf');
    fireEvent.change(fileInput, { target: { files: [existingFile] } });
    await screen.findByText('Selected Files:');

    let finishReading: (text: string) => void = () => undefined;
    const pendingText = new Promise<string>((resolve) => {
      finishReading = resolve;
    });
    const textFile = new File(['text'], 'new.txt');
    Object.defineProperty(textFile, 'text', { value: () => pendingText });
    fireEvent.change(fileInput, { target: { files: [textFile] } });
    await screen.findByText('Checking text source length…');

    fireEvent.click(screen.getByRole('button', { name: 'Remove file' }));
    finishReading('valid text');

    expect(await screen.findByText('new.txt')).toBeTruthy();
    expect(screen.queryByText('existing.pdf')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Upload 1 file(s)' }));
    await waitFor(() => expect(onUpload).toHaveBeenCalledWith([textFile]));
  });
});
