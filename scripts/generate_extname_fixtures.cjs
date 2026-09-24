// Reference outputs of Node's path.extname / path.basename(p, ext) for
// tests/unit/test_upload_helpers.py.
//
//   node scripts/generate_extname_fixtures.cjs \
//     > tests/fixtures/extname_cases.json
const path = require('node:path');

const paths = [
  'file.txt', 'file', '.bashrc', '..x', '...', '..', '.', 'a.', 'a..',
  'a.b.c', '/dir/file.txt', '/dir.x/file', 'dir/.hidden', 'x.tar.gz',
  '/a/b.', '.a.b', '..a..b', 'a/', 'a.b/', '/', '', 'Photo.JPG', 'a. b',
];
process.stdout.write(
  JSON.stringify(
    paths.map(p => {
      const ext = path.extname(p);
      return { path: p, ext, stem: path.basename(p, ext), base: path.basename(p) };
    }),
    null,
    1
  ) + '\n'
);
