// Reference outputs of the Node path handling used by jodit-nodejs for
// tests/unit/test_paths.py:
//   - BaseSource.getPath: path.resolve(normalizePath(path.join(root, rel)))
//   - flystorage PathNormalizerV1.normalizePath
//
//   node scripts/fixtures/generate_path_fixtures.cjs > tests/fixtures/path_cases.json
const path = require('node:path');

const normalizePath = p => p.replace(/\\/g, '/').replace(/\/+/g, '/');
const getPath = (root, rel) => path.resolve(normalizePath(path.join(root, rel)));

const storageNormalize = p => {
  if (/\p{C}+/u.test(p)) return { error: 'CorruptedPathError' };
  const normalized = path.join(...p.split('/'));
  if (normalized.indexOf('../') !== -1 || normalized == '..') {
    return { error: 'PathTraversalError' };
  }
  return { result: normalized === '.' ? '' : normalized };
};

const relatives = [
  '', './', '/', '.', '..', '../', '/..', 'a', '/a', 'a/', 'a/b', 'a/../b',
  'a/../../b', '../test2', '../test-evil', '..\\x', 'a\\..\\..\\x',
  'x/..\\..', '//a//b', 'a/./b/.', '\\\\a', '...', 'a..b', '../../../etc',
  '/private', 'sub/../sub2/./f.txt', 'a/b/../../..', '%2e%2e/x',
];
const roots = ['/srv/files/test', '/srv/files/test/', '//srv//files', '/'];

const getPathCases = [];
for (const root of roots) {
  for (const rel of relatives) {
    getPathCases.push({ root, rel, result: getPath(root, rel) });
  }
}

const storagePaths = [
  '', '/', '.', '..', '../a', 'a/..', 'a/../..', 'a//b', '/a/b/', './a',
  'a/./b', 'a\u0000b', 'a\tb', 'a​b', 'a b', 'ok/../fine', '...',
  'a/b/../../c', 'x/../../y', 'a/..b',
];

process.stdout.write(
  JSON.stringify(
    {
      getPath: getPathCases,
      storage: storagePaths.map(p => ({ path: p, ...storageNormalize(p) })),
    },
    null,
    1
  ) + '\n'
);
