// Replacement for src/tests/test-server.ts of jodit-nodejs: every test
// server is a jodit-python connector created by scripts/parity/server.py.
import fs from 'node:fs/promises';
import path from 'node:path';
import type { AppConfig } from '../types';
import type { AuthCallback } from '../middlewares/auth';

const testFilesPath = path.join(process.cwd(), './files/test');
const control = process.env.PARITY_SERVER ?? 'http://127.0.0.1:8099';

export interface TestServer {
  host: string;
  id?: string;
}

function functionKeys(value: unknown, prefix = ''): string[] {
  if (typeof value === 'function') {
    return [prefix || '<root>'];
  }
  if (value === null || typeof value !== 'object') {
    return [];
  }
  return Object.entries(value).flatMap(([key, item]) =>
    functionKeys(item, prefix ? `${prefix}.${key}` : key)
  );
}

export async function startTestServer(
  config?: Partial<AppConfig>,
  checkAuthentication?: AuthCallback
): Promise<TestServer> {
  await createTestDirectories();

  const full = {
    defaultFilesKey: 'files',
    allowPrivateNetworkUploads: true,
    sources: {
      test: {
        name: 'test',
        title: 'Test Files',
        root: testFilesPath,
        baseurl: 'http://localhost:8081/files/test/',
        defaultFilesKey: 'files'
      }
    },
    ...config
  };

  const functions = functionKeys(full);
  if (checkAuthentication !== undefined) {
    functions.push('checkAuthentication');
  }
  if (functions.length > 0) {
    throw new Error(`PARITY-UNSUPPORTED: functions in ${functions.join(', ')}`);
  }

  const response = await fetch(`${control}/__create`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(full)
  });
  const body = (await response.json()) as { id?: string; error?: string };
  if (body.id === undefined) {
    throw new Error(`PARITY-CONFIG: ${body.error}`);
  }
  return { host: `${control}/i/${body.id}`, id: body.id };
}

export async function stopTestServer(testServer: TestServer): Promise<void> {
  await cleanupTestFiles();
  if (testServer.id !== undefined) {
    await fetch(`${control}/__destroy/${testServer.id}`, { method: 'DELETE' });
  }
}

export async function createTestDirectories(): Promise<void> {
  await fs.mkdir(testFilesPath, { recursive: true });
  await fs.mkdir(path.join(testFilesPath, 'subdir'), { recursive: true });
}

export async function cleanupTestFiles(): Promise<void> {
  await fs.rm(testFilesPath, { recursive: true, force: true });
  await fs.rm(path.join(process.cwd(), './files/test2'), {
    recursive: true,
    force: true
  });
}

export async function createTestFile(
  fileName: string,
  content: string,
  basePath: string = ''
): Promise<void> {
  let filePath: string;
  if (
    basePath &&
    path.isAbsolute(basePath) &&
    basePath.includes(process.cwd())
  ) {
    filePath = path.join(basePath, fileName);
  } else {
    const relativePath = basePath.startsWith('/')
      ? basePath.substring(1)
      : basePath;
    filePath = path.join(testFilesPath, relativePath, fileName);
  }
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, content);
}
