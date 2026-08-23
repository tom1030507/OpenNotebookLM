import { spawn, spawnSync, type ChildProcess } from 'node:child_process';
import { createWriteStream } from 'node:fs';
import path from 'node:path';

import { runtime, serverEnvironment } from './runtime.js';

type ServiceName = 'backend' | 'frontend';

let stopping = false;

function start(service: ServiceName): ChildProcess {
  const isBackend = service === 'backend';
  const executable = isBackend ? (process.env.E2E_PYTHON ?? 'python') : process.execPath;
  const args = isBackend
    ? ['-m', 'scripts.e2e_server']
    : [
        path.join(runtime.repoRoot, 'frontend', 'node_modules', 'next', 'dist', 'bin', 'next'),
        'dev',
        '--turbopack',
        '--hostname',
        '127.0.0.1',
        '--port',
        '3100',
      ];
  const cwd = path.join(runtime.repoRoot, isBackend ? 'backend' : 'frontend');
  const log = createWriteStream(path.join(runtime.serverLogs, `${service}.log`), { flags: 'a' });
  const child = spawn(executable, args, {
    cwd,
    env: serverEnvironment,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
    detached: process.platform !== 'win32',
  });

  child.stdout?.on('data', (chunk: Buffer) => {
    process.stdout.write(chunk);
    log.write(chunk);
  });
  child.stderr?.on('data', (chunk: Buffer) => {
    process.stderr.write(chunk);
    log.write(chunk);
  });
  child.on('error', (error) => {
    log.end(`\nFailed to start ${service}: ${error.stack ?? error.message}\n`);
    process.exitCode = 1;
  });
  child.on('exit', (code, signal) => {
    log.end(`\n${service} exited code=${String(code)} signal=${String(signal)}\n`);
    process.exitCode = stopping ? 0 : (code ?? (signal ? 1 : 0));
  });
  return child;
}

function stopTree(child: ChildProcess, signal: NodeJS.Signals): void {
  if (child.pid === undefined) {
    return;
  }
  stopping = true;
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/pid', String(child.pid), '/t', '/f'], {
      stdio: 'ignore',
      windowsHide: true,
    });
    return;
  }
  try {
    process.kill(-child.pid, signal);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ESRCH') {
      throw error;
    }
  }
}

function main(): void {
  const service = process.argv[2];
  if (service !== 'backend' && service !== 'frontend') {
    throw new Error('Usage: run-service.ts backend|frontend');
  }
  const child = start(service);
  for (const signal of ['SIGINT', 'SIGTERM'] as const) {
    process.once(signal, () => stopTree(child, signal));
  }
}

main();
