import { test as base, expect } from '@playwright/test';

import { E2EApi } from './api.js';
import { BrowserDiagnostics } from './diagnostics.js';

type Fixtures = {
  api: E2EApi;
  browserDiagnostics: BrowserDiagnostics;
};

export const test = base.extend<Fixtures>({
  api: async ({ request }, use) => {
    await use(new E2EApi(request));
  },
  browserDiagnostics: [async ({ page }, use, testInfo) => {
    const diagnostics = new BrowserDiagnostics();
    diagnostics.install(page);
    await use(diagnostics);
    await diagnostics.verify(testInfo);
  }, { auto: true }],
});

export { expect };
