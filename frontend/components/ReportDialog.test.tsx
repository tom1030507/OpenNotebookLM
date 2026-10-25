// @vitest-environment jsdom

import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ReportDialog from './ReportDialog';
import api from '@/lib/api';

const report = {
  markdown: '# Report\n\nRainfall increased [Source 1].',
  citations: [{
    id: 1,
    document_id: 'doc-1',
    source: 'Rainfall study',
    text: 'Rainfall increased in the western region.',
  }],
};
let downloadedBlobs: Blob[] = [];

beforeEach(() => {
  downloadedBlobs = [];
  class TestURL extends URL {}
  TestURL.createObjectURL = vi.fn((blob: Blob) => {
    downloadedBlobs.push(blob);
    return 'blob:report';
  });
  TestURL.revokeObjectURL = vi.fn();
  vi.stubGlobal('URL', TestURL);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('ReportDialog', () => {
  it('offers five formats and only asks for custom instructions in Custom', () => {
    render(<ReportDialog projectId="project-1" projectName="Research" onClose={() => {}} />);

    const dialog = screen.getByRole('dialog', { name: 'Research report' });
    const format = within(dialog).getByLabelText('Report format') as HTMLSelectElement;
    expect(Array.from(format.options).map((option) => option.value)).toEqual([
      'briefing', 'study_guide', 'faq', 'timeline', 'custom',
    ]);
    expect(within(dialog).getByText(/concise executive summary/i)).toBeTruthy();
    expect(within(dialog).queryByLabelText('Custom instructions')).toBeNull();

    fireEvent.change(format, { target: { value: 'custom' } });
    const instructions = within(dialog).getByLabelText('Custom instructions') as HTMLTextAreaElement;
    expect(instructions.maxLength).toBe(500);
    expect(within(dialog).getByPlaceholderText('Describe the report you want')).toBeTruthy();
    expect((within(dialog).getByRole('button', { name: 'Generate report' }) as HTMLButtonElement).disabled)
      .toBe(true);
  });

  it('generates cited Markdown, saves it to notes, and downloads a safe filename', async () => {
    vi.spyOn(api, 'fetchProjectReport').mockResolvedValue(report);
    const onSave = vi.fn().mockResolvedValue(undefined);
    const clickedNames: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function click(
      this: HTMLAnchorElement,
    ) {
      clickedNames.push(this.download);
    });
    render(<ReportDialog
      projectId="project-1"
      projectName="../Research:/notes\u0000"
      documentIds={['doc-1']}
      onClose={() => {}}
      onSave={onSave}
    />);

    fireEvent.change(screen.getByLabelText('Report format'), { target: { value: 'custom' } });
    fireEvent.change(screen.getByLabelText('Custom instructions'), {
      target: { value: 'Explain the main finding' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Generate report' }));

    expect(await screen.findByRole('button', { name: 'Preview source 1' })).toBeTruthy();
    expect(api.fetchProjectReport).toHaveBeenCalledWith('project-1', {
      format: 'custom',
      instruction: 'Explain the main finding',
      document_ids: ['doc-1'],
    });
    fireEvent.click(screen.getByRole('button', { name: 'Preview source 1' }));
    expect((await screen.findByRole('tooltip')).textContent)
      .toContain('Rainfall increased in the western region.');

    fireEvent.click(screen.getByRole('button', { name: 'Download Markdown' }));
    expect(clickedNames).toHaveLength(1);
    expect(clickedNames[0]).toMatch(/\.md$/);
    expect(clickedNames[0]).not.toMatch(/[\\/:*?"<>|\u0000-\u001f\u007f]/);
    const reader = new FileReader();
    const downloadedMarkdown = new Promise<string>((resolve, reject) => {
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(reader.error);
    });
    reader.readAsText(downloadedBlobs[0]);
    const expectedMarkdown = `${report.markdown}\n\n**Sources**\n\n- Rainfall study\n  - [1]\n    > Rainfall increased in the western region.`;
    await expect(downloadedMarkdown).resolves.toBe(expectedMarkdown);

    fireEvent.click(screen.getByRole('button', { name: 'Save report to notes' }));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith(expectedMarkdown));
    expect(await screen.findByRole('button', { name: 'Saved to notes' })).toBeTruthy();
  });

  it('clears a generated report when its format changes', async () => {
    vi.spyOn(api, 'fetchProjectReport').mockResolvedValue(report);
    render(<ReportDialog projectId="project-1" projectName="Research" onClose={() => {}} />);

    fireEvent.click(screen.getByRole('button', { name: 'Generate report' }));
    expect(await screen.findByText('Generated report')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Report format'), { target: { value: 'faq' } });

    expect(screen.queryByText('Generated report')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Download Markdown' })).toBeNull();
  });

  it('clears a generated custom report when its instruction changes', async () => {
    vi.spyOn(api, 'fetchProjectReport').mockResolvedValue(report);
    render(<ReportDialog projectId="project-1" projectName="Research" onClose={() => {}} />);

    fireEvent.change(screen.getByLabelText('Report format'), { target: { value: 'custom' } });
    fireEvent.change(screen.getByLabelText('Custom instructions'), { target: { value: 'First request' } });
    fireEvent.click(screen.getByRole('button', { name: 'Generate report' }));
    expect(await screen.findByText('Generated report')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Custom instructions'), { target: { value: 'Updated request' } });

    expect(screen.queryByText('Generated report')).toBeNull();
  });

  it('locks report settings and generation while saving to notes', async () => {
    vi.spyOn(api, 'fetchProjectReport').mockResolvedValue(report);
    let finishSave!: () => void;
    const onSave = vi.fn(() => new Promise<void>((resolve) => { finishSave = resolve; }));
    render(<ReportDialog
      projectId="project-1"
      projectName="Research"
      onClose={() => {}}
      onSave={onSave}
    />);

    fireEvent.change(screen.getByLabelText('Report format'), { target: { value: 'custom' } });
    fireEvent.change(screen.getByLabelText('Custom instructions'), { target: { value: 'Explain the finding' } });
    fireEvent.click(screen.getByRole('button', { name: 'Generate report' }));
    expect(await screen.findByText('Generated report')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Save report to notes' }));

    expect(screen.getByRole('button', { name: 'Saving…' })).toBeTruthy();
    expect((screen.getByLabelText('Report format') as HTMLSelectElement).disabled).toBe(true);
    expect((screen.getByLabelText('Custom instructions') as HTMLTextAreaElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Generate report' }) as HTMLButtonElement).disabled)
      .toBe(true);
    finishSave();
    expect(await screen.findByRole('button', { name: 'Saved to notes' })).toBeTruthy();
  });

  it('does not show a late result after the dialog closes during generation', async () => {
    let resolve!: (value: typeof report) => void;
    vi.spyOn(api, 'fetchProjectReport').mockReturnValue(new Promise((done) => { resolve = done; }));
    const onClose = vi.fn();
    const view = render(<ReportDialog projectId="project-1" projectName="Research" onClose={onClose} />);

    fireEvent.click(screen.getByRole('button', { name: 'Generate report' }));
    expect(await screen.findByRole('status', { name: 'Generating report' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Close report dialog' }));
    view.unmount();
    resolve({ ...report, markdown: '# Late report' });
    await Promise.resolve();

    expect(onClose).toHaveBeenCalledOnce();
    expect(screen.queryByText('Late report')).toBeNull();
  });

  it('does not generate when the selection is explicitly empty', () => {
    render(<ReportDialog projectId="project-1" projectName="Research" documentIds={[]} onClose={() => {}} />);

    expect(screen.getByText(/select at least one source/i)).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Generate report' }) as HTMLButtonElement).disabled)
      .toBe(true);
  });
});
