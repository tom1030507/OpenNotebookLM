import { spawnSync } from 'node:child_process';
import { existsSync, rmSync } from 'node:fs';
import path from 'node:path';

import { expect, test } from '@playwright/test';

import { outputRoot, runtime } from '../support/runtime.js';

test('retains a passed run when another reporter raises an error', () => {
  const childRunId = `reporter-error-${runtime.runId}`;
  const childRoot = path.join(outputRoot, childRunId);
  const program = `
    import { existsSync } from 'node:fs';
    import CleanupReporter from './support/cleanup-reporter.ts';
    import { runtime } from './support/runtime.ts';

    const reporter = new CleanupReporter();
    reporter.onTestEnd({}, { status: 'passed' });
    reporter.onEnd({ status: 'passed' });
    reporter.onError?.({ message: 'reporter failed after tests passed' });
    await reporter.onExit();
    process.stdout.write(JSON.stringify({ exists: existsSync(runtime.root) }));
  `;

  try {
    const child = spawnSync(
      process.execPath,
      ['--import', 'tsx', '--input-type=module', '--eval', program],
      {
        cwd: path.join(runtime.repoRoot, 'e2e'),
        encoding: 'utf8',
        env: {
          ...process.env,
          E2E_KEEP_RUNTIME: '0',
          E2E_RUN_ID: childRunId,
        },
      },
    );

    expect(child.status, child.stderr).toBe(0);
    expect(JSON.parse(child.stdout)).toEqual({ exists: true });
  } finally {
    rmSync(childRoot, { recursive: true, force: true });
  }
});
