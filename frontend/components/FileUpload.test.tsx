// @vitest-environment jsdom

import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import FileUpload from './FileUpload';


describe('FileUpload', () => {
  it('accepts every supported source format and lists them in the drop area', () => {
    const { container } = render(<FileUpload onUpload={async () => undefined} />);
    const input = container.querySelector('input[type="file"]');

    expect(input?.getAttribute('accept')).toBe('.pdf,.txt,.md,.docx,.pptx,.xlsx,.epub,.png,.jpg,.jpeg,.webp,.mp3,.m4a,.wav,.ogg,.webm,.flac');
    expect(screen.getByText(/PDF, TXT, Markdown, Word, PowerPoint, Excel, EPUB, images, or audio/)).toBeTruthy();
  });
});
