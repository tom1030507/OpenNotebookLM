import { defineConfig, devices } from '@playwright/test';

import { runtime, serverEnvironment } from './support/runtime.js';

const isCI = process.env.CI === 'true';

export default defineConfig({
  testDir: './tests',
  timeout: process.env.FULL_RAG_E2E === '1' ? 10 * 60_000 : 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: isCI ? 1 : 0,
  retryStrategy: 'isolated',
  forbidOnly: isCI,
  failOnFlakyTests: isCI,
  outputDir: runtime.testResults,
  reporter: [
    ['list'],
    ['html', { outputFolder: runtime.htmlReport, open: 'never' }],
    ['./support/cleanup-reporter.ts'],
  ],
  use: {
    baseURL: runtime.frontendUrl,
    viewport: { width: 1440, height: 900 },
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: 'node --import tsx support/run-service.ts backend',
      cwd: import.meta.dirname,
      env: serverEnvironment,
      url: 'http://127.0.0.1:8100/healthz',
      reuseExistingServer: false,
      timeout: process.env.FULL_RAG_E2E === '1' ? 10 * 60_000 : 120_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      command: 'node --import tsx support/run-service.ts frontend',
      cwd: import.meta.dirname,
      env: serverEnvironment,
      url: 'http://127.0.0.1:3100/login',
      reuseExistingServer: false,
      timeout: 180_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
  projects: [
    {
      name: 'chromium-fast',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
      testIgnore: /full-rag\.spec\.ts/,
    },
    ...(process.env.FULL_RAG_E2E === '1' ? [{
      name: 'chromium-full-rag',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
      testMatch: /full-rag\.spec\.ts/,
    }] : []),
  ],
});
