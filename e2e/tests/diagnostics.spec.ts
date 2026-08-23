import { expect, test } from '@playwright/test';

import { isApplicationUrl } from '../support/diagnostics.js';

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
