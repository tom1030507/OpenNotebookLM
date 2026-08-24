import { expect, test, type Page } from '@playwright/test';

import { BrowserDiagnostics, isApplicationUrl } from '../support/diagnostics.js';

type PageEvent = 'console' | 'pageerror' | 'requestfailed' | 'response';
type Listener = (payload: unknown) => void;

function diagnosticsPage() {
  const listeners = new Map<PageEvent, Listener>();
  return {
    page: {
      on(event: PageEvent, listener: Listener) {
        listeners.set(event, listener);
        return this;
      },
    } as unknown as Page,
    emit(event: PageEvent, payload: unknown) {
      listeners.get(event)?.(payload);
    },
  };
}

test('accepts exact frontend origin and backend API or health boundaries', () => {
  const validUrls = [
    'http://localhost:3100/',
    'http://localhost:3100/login?from=%2F',
    'http://127.0.0.1:8100/api',
    'http://127.0.0.1:8100/api/',
    'http://127.0.0.1:8100/api/projects?limit=10',
    'http://127.0.0.1:8100/healthz',
    'http://127.0.0.1:8100/healthz?probe=browser',
  ];

  for (const url of validUrls) {
    expect(isApplicationUrl(url), url).toBe(true);
  }
});

test('rejects origin and backend path prefix collisions', () => {
  const invalidUrls = [
    'not a URL',
    'https://localhost:3100/login',
    'http://localhost:31000/login',
    'http://localhost.evil:3100/login',
    'http://127.0.0.1:8100/',
    'http://127.0.0.1:8100/apiary',
    'http://127.0.0.1:8100/api-v2/projects',
    'http://127.0.0.1:8100/healthz-extra',
    'http://127.0.0.1:8101/api/projects',
  ];

  for (const url of invalidUrls) {
    expect(isApplicationUrl(url), url).toBe(false);
  }
});

test('tolerates a registered auth-token 401 when its console error arrives first', async ({}, testInfo) => {
  const diagnostics = new BrowserDiagnostics();
  const harness = diagnosticsPage();
  diagnostics.install(harness.page);
  diagnostics.allowExpectedAuthToken401();

  harness.emit('console', {
    type: () => 'error',
    text: () => 'Failed to load resource: the server responded with a status of 401 (Unauthorized)',
  });
  harness.emit('response', {
    url: () => 'http://localhost:3100/api/auth/token',
    status: () => 401,
    request: () => ({ method: () => 'POST' }),
  });

  await expect(diagnostics.verify(testInfo)).resolves.toBeUndefined();
});

test('keeps unrelated 4xx-style console errors as diagnostics failures', async ({}, testInfo) => {
  const diagnostics = new BrowserDiagnostics();
  const harness = diagnosticsPage();
  diagnostics.install(harness.page);

  harness.emit('console', {
    type: () => 'error',
    text: () => 'Failed to load resource: the server responded with a status of 404 (Not Found)',
  });

  await expect(diagnostics.verify(testInfo)).rejects.toThrow('Unexpected browser diagnostics');
});
