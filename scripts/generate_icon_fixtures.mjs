// Reference SVG icons from jodit-nodejs src/helpers/image.ts for
// tests/unit/test_svg_icon.py.
//
//   node --experimental-strip-types scripts/generate_icon_fixtures.mjs \
//     ../jodit-nodejs/src/helpers/image.ts > tests/fixtures/icon_cases.json
const { generateIcon } = await import(new URL(process.argv[2], `file://${process.cwd()}/`).href);

const entries = [
  { path: 'docs', isDirectory: true },
  { path: 'a/report.pdf', isDirectory: false },
  { path: 'x.docx', isDirectory: false },
  { path: 'y.TXT', isDirectory: false },
  { path: 'archive.tar.gz', isDirectory: false },
  { path: 'z.xlsx', isDirectory: false },
  { path: 'm.mp4', isDirectory: false },
  { path: 'b.csv', isDirectory: false },
  { path: 'c.html', isDirectory: false },
  { path: 'd.7z', isDirectory: false },
];
const sizes = [[100, 100], [48, 64]];

const cases = entries.flatMap(entry =>
  sizes.map(([width, height]) => ({
    ...entry,
    width,
    height,
    result: generateIcon(entry, width, height),
  }))
);
process.stdout.write(JSON.stringify(cases, null, 1) + '\n');
