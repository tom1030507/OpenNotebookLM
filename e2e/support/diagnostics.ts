import type { Page, TestInfo } from '@playwright/test';

import { runtime } from './runtime.js';

const frontendOrigin = new URL(runtime.frontendUrl).origin;
const backendApiUrl = new URL(runtime.apiUrl);
const backendApiPath = backendApiUrl.pathname.replace(/\/$/, '');

export function isApplicationUrl(candidate: string): boolean {
  let url: URL;
  try {
    url = new URL(candidate);
  } catch {
    return false;
  }
  if (url.origin === frontendOrigin) {
    return true;
  }
  if (url.origin !== backendApiUrl.origin) {
    return false;
  }
  return (
    url.pathname === backendApiPath
    || url.pathname.startsWith(`${backendApiPath}/`)
    || url.pathname === '/healthz'
  );
}

export class BrowserDiagnostics {
  private readonly issues: string[] = [];

  install(page: Page): void {
    page.on('pageerror', (error) => this.issues.push(`pageerror: ${error.stack ?? error.message}`));
    page.on('console', (message) => {
      if (message.type() === 'error') {
        this.issues.push(`console.error: ${message.text()}`);
      }
    });
    page.on('requestfailed', (request) => {
      if (
        isApplicationUrl(request.url())
        && request.failure()?.errorText !== 'net::ERR_ABORTED'
      ) {
        this.issues.push(
          `requestfailed: ${request.method()} ${request.url()} ${request.failure()?.errorText ?? ''}`,
        );
      }
    });
    page.on('response', (response) => {
      if (isApplicationUrl(response.url()) && response.status() >= 500) {
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
