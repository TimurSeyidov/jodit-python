// Reference outputs of the JS helpers used by the files listing, for
// tests/unit/test_formatting.py.
//
//   npm install --no-save bytes@3.1.2 dayjs@1.11.18 slugify@1.6.6 zod@4.1.12
//   TZ=Europe/Moscow node scripts/generate_format_fixtures.mjs \
//     > tests/fixtures/format_cases.json
import bytes from 'bytes';
import dayjs from 'dayjs';
import slugify from 'slugify';
import { z } from 'zod';

const sizes = [
  0, 1, 11, 1000, 1023, 1024, 1025, 1152, 1536, 1587, 10240, 1048575,
  1048576, 1572864, 5767168, 1073741824, 1610612736, 1099511627776,
  1125899906842624, 2251799813685248, 123456789, 1126, 1127, 2047, 999999,
];

const formats = [
  'M/D/YYYY h:mm:ss A', 'YYYY-MM-DD HH:mm:ss', 'DD.MM.YY hh:mm a',
  'MMM MMMM d dd ddd dddd', 'H HH m s SSS', 'Z ZZ', '[Today is] dddd',
  'Y YYY', '[a]A[b]', '',
];
const times = [
  0, 1, 999, 1000.9, 1700000000123, 1700000000123.7, 1709251199999,
  1719792000000, 946684800000, -86400000, 32503680000000,
];

const names = [
  'image', 'My File', 'Привет мир', 'ёлка', 'Straße', 'café au lait',
  'a$b%c&d', 'x<y>z|w', 'foo--bar', '  spaced  ', 'tab\there', '日本語',
  'emoji😀name', 'a.b.c', "it's (1) [2] {3}", 'MÜNCHEN', 'Ælfred',
  'ƒunction', '∞ love ♥', 'dash-_-under', 'x+y~z!@:', '"quoted"',
  'ǅemal', 'ﬁle', '½ ¼', 'Ωmega', 'Ĳssel', '§1', 'a b', 'é',
];

const Mods = z.object({
  withFolders: z.union([z.boolean(), z.string()]).optional(),
  sortBy: z.enum(['name-asc', 'name-desc', 'changed-asc', 'changed-desc', 'size-asc', 'size-desc']).optional(),
  limit: z.union([z.number(), z.string()]).optional(),
  offset: z.union([z.number(), z.string()]).optional(),
  onlyImages: z.union([z.boolean(), z.string()]).optional(),
  foldersPosition: z.enum(['default', 'top', 'bottom']).optional(),
  filterWord: z.string().optional(),
});
const schemas = {
  files: z.object({
    source: z.string().optional(),
    path: z.string().optional(),
    mods: z.union([z.string(), Mods]).optional(),
  }),
  folders: z.object({
    source: z.string().optional(),
    path: z.string().optional(),
    dots: z.union([z.boolean(), z.literal('false'), z.literal('true')]).optional(),
  }),
  fileDownload: z.object({
    source: z.string().optional(),
    path: z.string().optional(),
    name: z.string(),
  }),
  getLocalFileByUrl: z.object({ url: z.string() }),
};
const inputs = [
  {}, { source: 't' }, { source: 1 }, { source: null }, { source: [] },
  { source: {} }, { source: true }, { path: 5 }, { mods: 'withFolders' },
  { mods: {} }, { mods: 5 }, { mods: [] }, { mods: null },
  { mods: { sortBy: 'x' } }, { mods: { sortBy: 'name-asc', limit: 5 } },
  { mods: { withFolders: 1 } }, { mods: { limit: true } },
  { mods: { foldersPosition: 'left' } }, { mods: { filterWord: 3 } },
  { mods: { withFolders: 'true', onlyImages: false, offset: '0' } },
  { dots: 'false' }, { dots: 'true' }, { dots: true }, { dots: '0' },
  { dots: 1 }, { name: 'a.txt' }, { name: 5 }, { name: null },
  { url: 'http://x/a.png' }, { url: 5 }, { source: 1, path: 2, name: 3 },
  { source: 1, mods: 5, dots: 1, url: [] },
];
const validation = [];
for (const [schema, zodSchema] of Object.entries(schemas)) {
  for (const input of inputs) {
    const result = zodSchema.safeParse(input);
    validation.push({
      schema,
      input,
      issues: result.success
        ? []
        : result.error.issues.map(issue => ({
            path: issue.path.join('.'),
            message: issue.message,
          })),
    });
  }
}

process.stdout.write(
  JSON.stringify(
    {
      bytes: sizes.map(size => ({ size, result: bytes.format(size) })),
      dayjs: formats.flatMap(format =>
        times.map(time => ({ format, time, result: dayjs(time).format(format) }))
      ),
      slugify: names.map(name => ({ name, result: slugify(name) })),
      validation,
    },
    null,
    1
  ) + '\n'
);
