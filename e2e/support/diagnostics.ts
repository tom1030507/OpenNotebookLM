import type { Page, TestInfo } from '@playwright/test';

import { runtime } from './runtime.js';

const frontendOrigin = new URL(runtime.frontendUrl).origin;
const backendApiUrl = new URL(runtime.apiUrl);
const backendApiPath = backendApiUrl.pathname.replace(/\/$/, '');
const authTokenUrl = `${runtime.browserApiUrl}/auth/token`;
const browserResource401 = /^Failed to load resource: the server responded with a status of 401\b/;

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
  private readonly pendingResource401Errors: string[] = [];
  private expectedAuthToken401Count = 0;
  private observedAuthToken401Count = 0;

  /** Register the one deliberate wrong-password response before submitting its form. */
  allowExpectedAuthToken401(): void {
    this.expectedAuthToken401Count += 1;
  }

  private isExpectedAuthToken401(response: { url(): string; status(): number; request(): { method(): string } }): boolean {
    return (
      response.url() === authTokenUrl
      && response.status() === 401
      && response.request().method() === 'POST'
      && this.observedAuthToken401Count < this.expectedAuthToken401Count
    );
  }

  install(page: Page): void {
    page.on('pageerror', (error) => this.issues.push(`pageerror: ${error.stack ?? error.message}`));
    page.on('console', (message) => {
      if (message.type() === 'error' && browserResource401.test(message.text())) {
        // The response event can arrive after Chrome's generic resource error.
        this.pendingResource401Errors.push(message.text());
      } else if (message.type() === 'error') {
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
      if (this.isExpectedAuthToken401(response)) {
        this.observedAuthToken401Count += 1;
      } else if (isApplicationUrl(response.url()) && response.status() >= 500) {
        this.issues.push(`http ${response.status()}: ${response.request().method()} ${response.url()}`);
      }
    });
  }

  async verify(testInfo: TestInfo): Promise<void> {
    const toleratedResource401Errors = Math.min(
      this.pendingResource401Errors.length,
      this.observedAuthToken401Count,
    );
    for (const message of this.pendingResource401Errors.slice(toleratedResource401Errors)) {
      this.issues.push(`console.error: ${message}`);
    }
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
