import { randomUUID } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';

export interface RuntimePaths {
  repoRoot: string;
  outputRoot: string;
  root: string;
  generated: string;
  serverLogs: string;
  testResults: string;
  htmlReport: string;
  runId: string;
  apiUrl: string;
  frontendUrl: string;
}

export const repoRoot = path.resolve(import.meta.dirname, '..', '..');
export const outputRoot = path.join(repoRoot, 'output', 'e2e');

export function assertSafeRuntimePath(candidatePath: string): string {
  const candidate = path.resolve(candidatePath);
  const relative = path.relative(path.resolve(outputRoot), candidate);
  const forbidden = new Set([
    path.resolve(repoRoot),
    path.resolve(outputRoot),
    path.resolve(os.homedir()),
    path.resolve(repoRoot, 'data'),
    path.resolve(repoRoot, 'uploads'),
  ]);
  if (
    !candidatePath.trim()
    || !relative
    || relative.startsWith(`..${path.sep}`)
    || relative === '..'
    || path.isAbsolute(relative)
    || forbidden.has(candidate)
  ) {
    throw new Error(`Unsafe E2E runtime path: ${candidatePath}`);
  }
  return candidate;
}

function pathsEqual(first: string, second: string): boolean {
  return path.relative(first, second) === '';
}

export function prepareRuntimeDirectory(
  repositoryPath: string,
  candidateOutputRoot: string,
  candidateRoot: string,
): boolean {
  const realRepository = realpathSync(repositoryPath);
  const outputParent = path.dirname(candidateOutputRoot);
  mkdirSync(outputParent, { recursive: true });
  const realOutputParent = realpathSync(outputParent);
  const expectedOutputParent = path.join(realRepository, 'output');
  if (!pathsEqual(expectedOutputParent, realOutputParent)) {
    throw new Error(`E2E output parent crosses a symbolic link or junction: ${realOutputParent}`);
  }
  if (!existsSync(candidateOutputRoot)) {
    mkdirSync(candidateOutputRoot);
  }
  const realOutput = realpathSync(candidateOutputRoot);
  const expectedOutput = path.join(realRepository, 'output', 'e2e');
  if (!pathsEqual(expectedOutput, realOutput)) {
    throw new Error(`E2E output root crosses a symbolic link or junction: ${realOutput}`);
  }
  const existed = existsSync(candidateRoot);
  if (!existed) {
    mkdirSync(candidateRoot);
  }
  const realRoot = realpathSync(candidateRoot);
  const realRelative = path.relative(realOutput, realRoot);
  if (!realRelative || realRelative.startsWith(`..${path.sep}`) || path.isAbsolute(realRelative)) {
    throw new Error(`Unsafe real E2E runtime path: ${realRoot}`);
  }
  return existed;
}

const runId = process.env.E2E_RUN_ID
  ?? `${Date.now().toString(36)}-${randomUUID().slice(0, 8)}`;
if (!/^[A-Za-z0-9._-]+$/.test(runId)) {
  throw new Error(`Invalid E2E_RUN_ID: ${runId}`);
}
process.env.E2E_RUN_ID = runId;

const root = assertSafeRuntimePath(path.join(outputRoot, runId));
export const runtime: RuntimePaths = {
  repoRoot,
  outputRoot,
  root,
  generated: path.join(root, 'generated'),
  serverLogs: path.join(root, 'server-logs'),
  testResults: path.join(root, 'test-results'),
  htmlReport: path.join(root, 'playwright-report'),
  runId,
  apiUrl: 'http://127.0.0.1:8100/api',
  frontendUrl: 'http://localhost:3100',
};

const existed = prepareRuntimeDirectory(repoRoot, outputRoot, runtime.root);
const realRoot = realpathSync(runtime.root);
const runtimeMarker = path.join(realRoot, '.e2e-runtime');
if (existed) {
  if (!existsSync(runtimeMarker) || readFileSync(runtimeMarker, 'utf8') !== runtime.runId) {
    throw new Error(`Existing E2E runtime has no matching marker: ${realRoot}`);
  }
} else {
  writeFileSync(runtimeMarker, runtime.runId, 'utf8');
}
for (const directory of [runtime.generated, runtime.serverLogs, runtime.testResults]) {
  mkdirSync(directory, { recursive: true });
}

export function safeRemoveRuntime(candidatePath: string): void {
  const safePath = assertSafeRuntimePath(candidatePath);
  if (!existsSync(safePath)) {
    return;
  }
  const realOutput = realpathSync(outputRoot);
  const realCandidate = realpathSync(safePath);
  const realRelative = path.relative(realOutput, realCandidate);
  if (!realRelative || realRelative.startsWith(`..${path.sep}`) || path.isAbsolute(realRelative)) {
    throw new Error(`Unsafe real E2E runtime path: ${realCandidate}`);
  }
  const marker = path.join(realCandidate, '.e2e-runtime');
  if (!existsSync(marker) || readFileSync(marker, 'utf8') !== runtime.runId) {
    throw new Error(`Missing or invalid E2E runtime marker: ${marker}`);
  }
  rmSync(safePath, {
    recursive: true,
    force: true,
    maxRetries: 5,
    retryDelay: 200,
  });
}

const inheritedEnvironment = Object.fromEntries(
  Object.entries(process.env).filter((entry): entry is [string, string] => entry[1] !== undefined),
);
export const serverEnvironment: Record<string, string> = {
  ...inheritedEnvironment,
  E2E_RUNTIME_ROOT: runtime.root,
  E2E_API_URL: runtime.apiUrl,
  E2E_FRONTEND_URL: runtime.frontendUrl,
  NEXT_PUBLIC_API_URL: runtime.apiUrl,
};
