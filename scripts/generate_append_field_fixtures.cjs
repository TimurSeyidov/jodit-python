// Reference outputs of append-field (used by multer) for
// tests/unit/test_append_field.py.
//
//   npm install --no-save append-field@1.0.0
//   node scripts/generate_append_field_fixtures.cjs \
//     > tests/fixtures/append_field_cases.json
const appendField = require('append-field');

const manual = [
  [['a', '1']],
  [['a', '1'], ['a', '2'], ['a', '3']],
  [['mods[sortBy]', 'name'], ['mods[offset]', '10']],
  [['tags[]', 'x'], ['tags[]', 'y']],
  [['files[0]', 'a'], ['files[1]', 'b']],
  [['files[2]', 'c']],
  [['a[0]', 'x'], ['a[b]', 'y']],
  [['a', 'x'], ['a[b]', 'y']],
  [['a[b]', 'y'], ['a', 'x']],
  [['a[]x', '1']],
  [['[a]', '1']],
  [['a[b][c][d]', '1']],
  [['a[0][b]', '1'], ['a[0][c]', '2'], ['a[1][b]', '3']],
  [['a[', '1']],
  [['a[]', '1'], ['a', '2']],
];

const tokens = ['a', 'b', '[', ']', '[]', '[0]', '[1]', '[3]', '[a]', '[b]', 'x'];
const values = ['1', '2', 'v'];
let seed = 7;
const random = () => {
  seed = (seed * 1103515245 + 12345) % 2147483648;
  return seed / 2147483648;
};
const pick = list => list[Math.floor(random() * list.length)];
const fuzz = [];
for (let n = 0; n < 800; n += 1) {
  const fields = [];
  const count = 1 + Math.floor(random() * 4);
  for (let i = 0; i < count; i += 1) {
    let key = '';
    const length = 1 + Math.floor(random() * 4);
    for (let j = 0; j < length; j += 1) key += pick(tokens);
    fields.push([key, pick(values)]);
  }
  fuzz.push(fields);
}

const cases = [...manual, ...fuzz].map(fields => {
  const store = Object.create(null);
  for (const [key, value] of fields) appendField(store, key, value);
  return { fields, result: JSON.parse(JSON.stringify(store)) };
});

process.stdout.write(JSON.stringify(cases, null, 1) + '\n');
