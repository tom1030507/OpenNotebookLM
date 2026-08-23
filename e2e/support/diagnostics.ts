import type { Page, TestInfo } from '@playwright/test';

import { runtime } from './runtime.js';

export class BrowserDiagnostics {
  private readonly issues: string[] = [];

  private isApplicationUrl(url: string): boolean {
    return url.startsWith(runtime.frontendUrl) || url.startsWith(runtime.apiUrl);
  }

  install(page: Page): void {
    page.on('pageerror', (error) => this.issues.push(`pageerror: ${error.stack ?? error.message}`));
    page.on('console', (message) => {
      if (message.type() === 'error') {
        this.issues.push(`console.error: ${message.text()}`);
      }
    });
    page.on('requestfailed', (request) => {
      if (
        this.isApplicationUrl(request.url())
        && request.failure()?.errorText !== 'net::ERR_ABORTED'
      ) {
        this.issues.push(
          `requestfailed: ${request.method()} ${request.url()} ${request.failure()?.errorText ?? ''}`,
        );
      }
    });
    page.on('response', (response) => {
      if (this.isApplicationUrl(response.url()) && response.status() >= 500) {
        this.issues.push(`http ${response.status()}: ${response.request().method()} ${response.url()}`);
      }
    });
  }

  async verify(testInfo: TestInfo): Promise<void> {
    if (this.issues.length === 0) {
      return;
    }
    const body = Buffer.from(`${this.issues.join('\n')}\n`, 'utf8');
    await testInfo.attach('unexpected-browser-diagnostics.txt', {
      body,
      contentType: 'text/plain',
    });
    if (testInfo.status === undefined || testInfo.status === testInfo.expectedStatus) {
      throw new Error(`Unexpected browser diagnostics:\n${this.issues.join('\n')}`);
    }
  }
}
