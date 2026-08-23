import type { FullResult, Reporter, TestCase, TestResult } from '@playwright/test/reporter';

import { runtime, safeRemoveRuntime } from './runtime.js';

export default class CleanupReporter implements Reporter {
  private hadFailedAttempt = false;
  private succeeded = false;

  onTestEnd(_test: TestCase, result: TestResult): void {
    if (!['passed', 'skipped'].includes(result.status)) {
      this.hadFailedAttempt = true;
    }
  }

  onEnd(result: FullResult): void {
    this.succeeded = result.status === 'passed' && !this.hadFailedAttempt;
  }

  async onExit(): Promise<void> {
    if (this.succeeded && process.env.E2E_KEEP_RUNTIME !== '1') {
      try {
        safeRemoveRuntime(runtime.root);
      } catch (error) {
        process.stderr.write(`E2E cleanup warning: ${String(error)}\n`);
      }
    }
  }
}
