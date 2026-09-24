// Reference results of the jodit-nodejs generatePdf/generateDocx schemas
// for tests/unit/test_documents.py. Run next to a `schemas/` folder with
// copies of src/v1/generate-*/schemes/*.schema.ts and zod installed:
//
//   node --experimental-strip-types generate_document_schema_fixtures.mjs \
//     > tests/fixtures/document_schema_cases.json
const load = async name =>
  import(new URL(`schemas/${name}.schema.ts`, `file://${process.cwd()}/`).href);
const { GeneratePdfQuerySchema } = await load('generate-pdf');
const { GenerateDocxQuerySchema } = await load('generate-docx');

const inputs = [
  {}, { html: '' }, { html: 5 }, { html: '<p>x</p>' }, { html: ' ' },
  { html: 'x', options: 'str' }, { html: 'x', options: { format: 'A5' } },
  { html: 'x', options: { page_orientation: 'up', defaultFont: 'arial' } },
  { html: 'x', options: { format: 'Letter', page_orientation: 'landscape' } },
  { html: 'x', options: { defaultFont: 'times' } }, { html: 'x', options: 5 },
  { html: 'x', options: [] }, { html: 'x', options: null },
  { source: 1, html: 'x' }, { html: null, options: 1 },
];
const cases = [];
for (const [schema, zodSchema] of [
  ['generatePdf', GeneratePdfQuerySchema],
  ['generateDocx', GenerateDocxQuerySchema],
]) {
  for (const input of inputs) {
    const result = zodSchema.safeParse(input);
    cases.push({
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
process.stdout.write(JSON.stringify(cases, null, 1) + '\n');
