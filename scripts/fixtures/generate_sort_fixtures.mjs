// Reference orders of jodit-nodejs sortByMode for
// tests/unit/test_listing_helpers.py.
//
//   node --experimental-strip-types scripts/fixtures/generate_sort_fixtures.mjs \
//     ../jodit-nodejs/src/services/file-manager/sort-files.ts \
//     > tests/fixtures/sort_cases.json
const { sortByMode } = await import(new URL(process.argv[2], `file://${process.cwd()}/`).href);

let seed = 11;
const random = () => {
  seed = (seed * 1103515245 + 12345) % 2147483648;
  return seed / 2147483648;
};
const pick = list => list[Math.floor(random() * list.length)];
const names = ['a', 'B', 'b', 'c.txt', 'Z', 'ä', 'é.png', '10', '9', 'x_y', 'X', 'a', 'dir', '😀', '￿'];
const modes = ['name-asc', 'name-desc', 'changed-asc', 'changed-desc', 'size-asc', 'size-desc', 'unknown'];
const positions = ['default', 'top', 'bottom'];

const cases = [];
for (let n = 0; n < 400; n += 1) {
  const count = Math.floor(random() * 30);
  const items = Array.from({ length: count }, (_, index) => ({
    id: index,
    name: pick(names),
    size: pick([0, 1, 5, 5, 100]),
    mtime: pick([0, 1000, 1000, 2000.5, 3000]),
    isDirectory: random() < 0.3,
  }));
  const sortBy = pick(modes);
  const foldersPosition = pick(positions);
  const files = items.map(item => ({ ...item, stat: { isDirectory: item.isDirectory } }));
  sortByMode(files, sortBy, { foldersPosition });
  cases.push({ items, sortBy, foldersPosition, order: files.map(file => file.id) });
}
process.stdout.write(JSON.stringify(cases) + '\n');
