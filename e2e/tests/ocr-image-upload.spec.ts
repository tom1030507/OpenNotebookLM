import { test, expect } from '../support/fixtures.js';
import { openAddSourceDialog, setupWorkspace } from '../support/ui.js';

test('browser accepts and lists a PNG source', async ({ api, page }, testInfo) => {
  await setupWorkspace(api, page, testInfo, 'ocr-image-ui');
  const dialog = await openAddSourceDialog(page);
  const input = dialog.locator('input[type="file"]');

  // The accepted types come from the backend's upload settings and grow with
  // every new source format, so this test pins only the image formats it owns.
  await expect(dialog.getByText(/^Supported file types: .*\.png/)).toBeVisible();
  const accepted = (await input.getAttribute('accept'))?.split(',') ?? [];
  expect(accepted).toEqual(expect.arrayContaining(['.png', '.jpg', '.jpeg', '.webp']));
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
