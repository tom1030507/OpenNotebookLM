import { createRequire } from 'node:module';
import { writeFile } from 'node:fs/promises';

const { PDFDocument, StandardFonts, rgb } = createRequire(import.meta.url)('pdf-lib') as typeof import('pdf-lib');

export async function generatePdf(
  outputPath: string,
  title: string,
  fact: string,
): Promise<void> {
  const document = await PDFDocument.create();
  const font = await document.embedFont(StandardFonts.Helvetica);
  const bold = await document.embedFont(StandardFonts.HelveticaBold);
  const page = document.addPage([612, 792]);
  page.drawText(title, { x: 72, y: 700, size: 20, font: bold, color: rgb(0.1, 0.1, 0.1) });
  page.drawText(fact, { x: 72, y: 650, size: 12, font, color: rgb(0.1, 0.1, 0.1) });
  page.drawText('Generated locally for deterministic browser testing.', {
    x: 72,
    y: 625,
    size: 10,
    font,
    color: rgb(0.3, 0.3, 0.3),
  });
  await writeFile(outputPath, await document.save());
}
