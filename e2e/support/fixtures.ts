import { test as base, expect } from '@playwright/test';

import { BrowserDiagnostics } from './diagnostics.js';

type AutomaticFixtures = {
  browserDiagnostics: BrowserDiagnostics;
};

export const test = base.extend<AutomaticFixtures>({
  browserDiagnostics: [async ({ page }, use, testInfo) => {
    const diagnostics = new BrowserDiagnostics();
    diagnostics.install(page);
    await use(diagnostics);
    await diagnostics.verify(testInfo);
  }, { auto: true }],
});

export { expect };
