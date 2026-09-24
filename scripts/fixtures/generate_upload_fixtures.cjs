// Reference outputs of sanitize-filename and bytes.parse for
// tests/unit/test_upload_helpers.py.
//
//   npm install --no-save sanitize-filename@1.6.3 bytes@3.1.2
//   node scripts/fixtures/generate_upload_fixtures.cjs \
//     > tests/fixtures/upload_cases.json
const sanitize = require('sanitize-filename');
const bytes = require('bytes');

const names = [
  'file.txt', 'my photo.png', 'a/b\\c.txt', 'what?.txt', '<tag>.html',
  'x:y*z|w"q.txt', 'ctrl\u0001\u001f\u0080\u009fchars', '.', '..', '...',
  'con', 'CON.txt', 'nul.tar.gz', 'com1', 'lpt9.x', 'coma', 'trailing. ',
  'dots...', ' leading', 'Привет мир.docx', '日本語.pdf', '😀emoji.png',
  'x'.repeat(300), 'я'.repeat(200), '😀'.repeat(100), '', '../../etc/passwd',
  'a\u0000b', 'ok_name-1.JPG', '. .', 'aux.', ' nbsp',
];
const limits = [
  '8mb', '8MB', '1.5kb', '10 kb', '+2gb', '-1mb', '1tb', '1pb', '500',
  '500b', '12abc', 'abc', '', '0.1kb', '1.2.3mb', ' 5kb', '5kb ', '3e2',
  '  42', '0x10', '1024', '2.5', '7 MB',
];

process.stdout.write(
  JSON.stringify(
    {
      sanitize: names.map(name => ({
        name,
        underscore: sanitize(name, { replacement: '_' }),
        plain: sanitize(name),
      })),
      bytes: limits.map(value => ({ value, result: bytes.parse(value) })),
    },
    null,
    1
  ) + '\n'
);
