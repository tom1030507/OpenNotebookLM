import { test, expect } from '../support/fixtures.js';
import { openAddSourceDialog, setupWorkspace } from '../support/ui.js';

test('browser accepts and lists a PNG source', async ({ api, page }, testInfo) => {
  await setupWorkspace(api, page, testInfo, 'ocr-image-ui');
  const dialog = await openAddSourceDialog(page);
  const input = dialog.locator('input[type="file"]');

  await expect(input).toHaveAttribute(
    'accept',
    '.pdf,.txt,.md,.docx,.pptx,.xlsx,.epub,.png,.jpg,.jpeg,.webp',
  );
  await expect(dialog.getByText(/PDF, TXT, Markdown, Word, PowerPoint, Excel, EPUB, or images/))
    .toBeVisible();
  await input.setInputFiles({
    name: 'whiteboard.png',
    mimeType: 'image/png',
    buffer: Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+nmioAAAAASUVORK5CYII=',
      'base64',
    ),
  });

  await expect(dialog.getByText('whiteboard.png', { exact: true })).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Upload 1 file(s)', exact: true }))
    .toBeEnabled();
});
