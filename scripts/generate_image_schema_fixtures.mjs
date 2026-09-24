// Reference results of the jodit-nodejs image action schemas (zod 4) for
// tests/unit/test_image_validation.py. Run from a directory with
// zod@4.1.12 and @asteasolutions/zod-to-openapi@8 installed, next to a
// `schemas/` folder holding copies of src/v1/image-*/schemes/*.schema.ts:
//
//   node --experimental-strip-types generate_image_schema_fixtures.mjs \
//     > tests/fixtures/image_schema_cases.json
const load = async name =>
  import(new URL(`schemas/${name}.schema.ts`, `file://${process.cwd()}/`).href);
const { ImageResizeQuerySchema } = await load('image-resize');
const { ImageCropQuerySchema } = await load('image-crop');
const { ImageSaveQuerySchema } = await load('image-save');
const { ImageLoadQuerySchema } = await load('image-load');

const base = { name: 'a.jpg' };
const boxes = [
  undefined, 'x', [], {}, { w: '10', h: '20' }, { w: 10, h: 20 },
  { w: '10.7', h: '5px' }, { w: 'abc', h: 1 }, { w: 1.5, h: 2 },
  { w: 0, h: -1 }, { w: '-3', h: '0' }, { x: '0', y: '0', w: '5', h: '5' },
  { x: -1, y: 2.5, w: 5, h: 5 }, { x: '1', y: 'q', w: '5', h: '5' },
  { x: 1, y: 1, w: 1 }, { w: null, h: 1 }, { w: true, h: 1 },
  { x: 0, y: 0, w: 1e21, h: 3 }, { w: 3, h: ' 4 ' },
  { x: -2.5, y: -1e21, w: -1.5, h: 1 }, { x: '-0', y: '09', w: '0x1f', h: '1e3' },
];
const inputs = [
  {}, { source: 1 }, { ...base, path: 2 }, { ...base, newname: 5 },
  { name: 5, newname: [] },
  ...boxes.map(box => (box === undefined ? { ...base } : { ...base, box })),
  { ...base, 'box[w]': '7', 'box[h]': '8' },
  { ...base, 'box[x]': '1', 'box[y]': '2', 'box[w]': '7', 'box[h]': '8' },
  { ...base, 'box[w]': 7, 'box[h]': 'z' },
  { source: 1, box: { w: 'q' } },
];

const run = (schema, input) => {
  const result = schema.safeParse(input);
  if (result.success) {
    return { box: result.data.box ?? null };
  }
  return {
    issues: result.error.issues.map(issue => ({
      path: issue.path.join('.'),
      message: issue.message,
    })),
  };
};

const cases = [];
for (const [schema, zodSchema] of Object.entries({
  imageResize: ImageResizeQuerySchema,
  imageCrop: ImageCropQuerySchema,
  imageSave: ImageSaveQuerySchema,
  imageLoad: ImageLoadQuerySchema,
})) {
  for (const input of inputs) {
    cases.push({ schema, input, ...run(zodSchema, input) });
  }
}
process.stdout.write(JSON.stringify(cases, null, 1) + '\n');
