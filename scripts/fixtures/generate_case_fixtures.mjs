// Reference outputs of change-case for tests/unit/test_case.py.
//
//   npm install --no-save change-case@5.4.4
//   node scripts/fixtures/generate_case_fixtures.mjs > tests/fixtures/case_cases.json
import { camelCase, constantCase } from 'change-case';

const manual = [
  '', 'files', 'fileUpload', 'file-upload', 'FILE_UPLOAD', 'getLocalFileByUrl',
  'fileUploadRemote', 'generatePdf', 'allow_FILE_UPLOAD', 'allow_FOLDER_TREE',
  'allow_GENERATE_DOCX', 'XMLHttpRequest', 'version2Beta', 'a1B2C', 'ABCdef',
  '  spaced  words ', '__proto__', 'foo--bar__baz', 'é-Ümlaut', 'straße',
  'ÀÉÎõü', 'x9', '9x', 'allow_2FA', 'HTML5Parser',
];
const tokens = ['a', 'B', 'c', 'D', '1', '_', '-', ' ', 'É', 'é', 'ß', 'xY', 'ZZ', '.'];
let seed = 3;
const random = () => {
  seed = (seed * 1103515245 + 12345) % 2147483648;
  return seed / 2147483648;
};
const fuzz = [];
for (let n = 0; n < 1000; n += 1) {
  let text = '';
  const length = 1 + Math.floor(random() * 10);
  for (let i = 0; i < length; i += 1) {
    text += tokens[Math.floor(random() * tokens.length)];
  }
  fuzz.push(text);
}

const cases = [...manual, ...fuzz].map(input => ({
  input,
  constant: constantCase(input),
  camel: camelCase(input),
}));
process.stdout.write(JSON.stringify(cases, null, 1) + '\n');
