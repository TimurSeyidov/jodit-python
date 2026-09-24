// Reference outputs of qs.parse for tests/unit/test_qs.py.
//
//   npm install --no-save qs@6.16.0
//   node scripts/fixtures/generate_qs_fixtures.cjs > tests/fixtures/qs_cases.json
//
// "query" uses the qs defaults (Express query strings), "body" uses the
// options body-parser passes for extended urlencoded bodies.
const qs = require('qs');

const seq = (key, count) =>
  Array.from({ length: count }, (_, i) => `${key}=${i}`).join('&');

const manual = [
  '', 'a=1', 'a[b][c]=1', 'a[]=1&a[]=2', 'a=1&a=2', 'a[1]=b',
  'a[0]=x&a[1]=y', 'a[19]=x', 'a[20]=x', 'a[21]=x', 'a[]=b&a[x]=c',
  'a[b]=1&a[b]=2', 'a[b][c][d][e][f][g][h]=1', 'a+b=c+d&e=%20',
  '[x]=1', 'a[b=1', 'a[]=1&a[0]=2', 'mods[withFolders]=true&mods[offset]=10',
  'a=1&a[b]=2', 'a[b]=2&a=1', 'x=', '=y', 'x', 'a[1]=q&a[0]=p',
  'a[0][b]=1&a[0][c]=2', 'a[][b]=1&a[][b]=2', 'a[b][]=1&a[b][]=2',
  'a[][b]=1&a[][c]=2', 'a=1&a[b]=2&a[c]=3', 'a[]=x&a[][b]=1',
  'a[b]=1&a[]=2', 'a=1&a=2&a[b]=3', 'a=%E2%9C%93', 'a=%E2', 'a=%zz',
  'a%5Bb%5D=1', 'a[b=c]=d', 'toString=1', 'a[toString]=1',
  '__proto__[x]=1', 'a[__proto__]=1', 'a=toString&a[b]=1', 'a[[b]]=1',
  'a[b]c[d]=1', 'a[]=', 'a[]=&a[]=1', 'b=1&1=a&0=z',
  'options[format]=A4&options[margin][top]=10',
  Array.from({ length: 25 }, (_, i) => `a[]=${i}`).join('&'),
  Array.from({ length: 25 }, (_, i) => `a=${i}`).join('&'),
  Array.from({ length: 25 }, (_, i) => `a[${i}]=${i}`).join('&'),
  'a' + '[b]'.repeat(40) + '=1',
  // arrayLimit overflow paths of utils.merge / utils.combine.
  seq('a[]', 20) + '&a=x',
  seq('a[]', 25) + '&a=x',
  'a=x&' + seq('a[]', 20),
  'a=x&' + seq('a[]', 25),
  'a[0]=x&' + seq('a[]', 20),
  seq('a[]', 25) + '&a[b]=1',
  'a[b]=1&' + seq('a[]', 25),
  seq('a[]', 25) + '&' + seq('a[]', 3),
  seq('a', 25) + '&a[b]=1&a=z',
  'a[4294967295]=x&a[]=y',
  'a[99]=x&a[100]=y&a[b]=z',
  'a[][3]=x',
  'a[][3]=x&a[][1]=y',
  Array.from({ length: 1005 }, (_, i) => `k${i}=${i}`).join('&'),
];

// Deterministic fuzzing over tokens that exercise brackets, indices,
// duplicates, escapes and prototype keys.
const tokens = [
  'a', 'b', 'c', '0', '1', '5', '19', '20', '21', '[', ']', '[]', '[a]',
  '[b]', '[0]', '[1]', '[20]', '[21]', '=', '=', '=', '&', '&', 'x',
  'y', '', '%5B', '%5D', '+', '%20', 'toString', '[toString]',
];
let seed = 42;
const random = () => {
  seed = (seed * 1103515245 + 12345) % 2147483648;
  return seed / 2147483648;
};
const fuzz = [];
for (let n = 0; n < 1500; n += 1) {
  const length = 1 + Math.floor(random() * 14);
  let text = '';
  for (let i = 0; i < length; i += 1) {
    text += tokens[Math.floor(random() * tokens.length)];
  }
  fuzz.push(text);
}

const count = body => body.split('&').length;
const run = (input, options) => {
  try {
    return { result: qs.parse(input, options) };
  } catch (error) {
    return { error: error.constructor.name };
  }
};

const cases = [...manual, ...fuzz].map(input => ({
  input,
  query: run(input, {}),
  body: run(input, {
    allowPrototypes: true,
    arrayLimit: Math.max(100, count(input)),
    depth: 32,
    parameterLimit: 1000,
    strictDepth: true,
  }),
}));

process.stdout.write(JSON.stringify(cases, null, 1) + '\n');
