import { existsSync, mkdirSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import path from 'node:path';

import { expect, test } from '@playwright/test';

import {
  assertSafeRuntimePath,
  outputRoot,
  prepareRuntimeDirectory,
  runtime,
  safeRemoveRuntime,
} from '../support/runtime.js';

test('accepts only strict children of output/e2e', () => {
  const run = path.join(outputRoot, 'run-safe-123');

  expect(assertSafeRuntimePath(run)).toBe(path.resolve(run));
  expect(() => assertSafeRuntimePath(outputRoot)).toThrow(/unsafe e2e runtime/i);
  expect(() => assertSafeRuntimePath(path.dirname(outputRoot))).toThrow(/unsafe e2e runtime/i);
  expect(() => assertSafeRuntimePath(path.resolve(outputRoot, '..', '..', 'uploads'))).toThrow(
    /unsafe e2e runtime/i,
  );
});

test('requires a matching marker before recursive cleanup', () => {
  const candidate = path.join(outputRoot, `cleanup-contract-${runtime.runId}`);
  mkdirSync(candidate, { recursive: true });
  writeFileSync(path.join(candidate, '.e2e-runtime'), 'wrong-run', 'utf8');

  expect(() => safeRemoveRuntime(candidate)).toThrow(/marker/i);
  expect(existsSync(candidate)).toBe(true);

  writeFileSync(path.join(candidate, '.e2e-runtime'), runtime.runId, 'utf8');
  safeRemoveRuntime(candidate);
  expect(existsSync(candidate)).toBe(false);
});

test('rejects an output link before creating a run outside its repository', ({}, testInfo) => {
  const sandbox = testInfo.outputPath('linked-output');
  const repository = path.join(sandbox, 'repo');
  const outputParent = path.join(repository, 'output');
  const linkedOutput = path.join(outputParent, 'e2e');
  const outside = path.join(sandbox, 'outside');
  const escapedRun = path.join(outside, 'must-not-exist');
  mkdirSync(outputParent, { recursive: true });
  mkdirSync(outside, { recursive: true });
  try {
    symlinkSync(outside, linkedOutput, process.platform === 'win32' ? 'junction' : 'dir');
  } catch (error) {
    test.skip(true, `This host cannot create a directory link: ${String(error)}`);
    return;
  }

  expect(() => prepareRuntimeDirectory(
    repository,
    linkedOutput,
    path.join(linkedOutput, 'must-not-exist'),
  )).toThrow(/symbolic link|junction/i);
  expect(existsSync(escapedRun)).toBe(false);
});

test('rejects an arbitrary output root before creating its parent', ({}, testInfo) => {
  const sandbox = testInfo.outputPath('outside-output-root');
  const repository = path.join(sandbox, 'repo');
  const outsideParent = path.join(sandbox, 'must-not-create');
  const outsideOutput = path.join(outsideParent, 'e2e');
  mkdirSync(repository, { recursive: true });

  try {
    expect(() => prepareRuntimeDirectory(
      repository,
      outsideOutput,
      path.join(outsideOutput, 'run-unsafe'),
    )).toThrow(/unsafe|output/i);
    expect(existsSync(outsideParent)).toBe(false);
  } finally {
    rmSync(outsideParent, { recursive: true, force: true });
  }
});

test('rejects a nested junction before creating its escaped child', ({}, testInfo) => {
  const sandbox = testInfo.outputPath('nested-output-link');
  const repository = path.join(sandbox, 'repo');
  const trustedOutput = path.join(repository, 'output', 'e2e');
  const outside = path.join(sandbox, 'outside');
  const nestedLink = path.join(trustedOutput, 'nested-link');
  const escapedChild = path.join(outside, 'must-not-create');
  mkdirSync(trustedOutput, { recursive: true });
  mkdirSync(outside, { recursive: true });
  try {
    symlinkSync(outside, nestedLink, process.platform === 'win32' ? 'junction' : 'dir');
  } catch (error) {
    test.skip(true, `This host cannot create a directory link: ${String(error)}`);
    return;
  }

  try {
    expect(() => prepareRuntimeDirectory(
      repository,
      trustedOutput,
      path.join(nestedLink, 'must-not-create'),
    )).toThrow(/unsafe|symbolic link|junction/i);
    expect(existsSync(escapedChild)).toBe(false);
  } finally {
    rmSync(escapedChild, { recursive: true, force: true });
    rmSync(nestedLink, { recursive: true, force: true });
  }
});
