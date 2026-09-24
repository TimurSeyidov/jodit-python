// Open the jodit-nodejs demo page in headless Chrome and record every
// request to the connector with its answer.
//
// Usage: node demo.mjs <page-url> <connector-url> <out-prefix>
import fs from 'node:fs';
import puppeteer from 'puppeteer-core';

const [pageUrl, connector, out] = process.argv.slice(2);
const chrome =
  process.env.CHROME_PATH ??
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

const browser = await puppeteer.launch({
  executablePath: chrome,
  headless: true,
  args: ['--no-sandbox']
});
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 900 });

const log = [];
const failed = [];
const consoleErrors = [];
page.on('console', message => {
  if (message.type() === 'error') consoleErrors.push(message.text());
});
page.on('pageerror', error => consoleErrors.push(String(error)));
page.on('response', async response => {
  const request = response.request();
  if (response.status() >= 400) {
    failed.push(`${response.status()} ${request.url()}`);
  }
  if (!request.url().startsWith(connector)) return;
  let body = null;
  try {
    body = await response.text();
  } catch {
    body = null;
  }
  log.push({
    method: request.method(),
    url: request.url().slice(connector.length),
    postData: request.postData() ?? null,
    status: response.status(),
    contentType: response.headers()['content-type'] ?? null,
    body
  });
});

const settle = () => new Promise(resolve => setTimeout(resolve, 1500));

await page.goto(pageUrl, { waitUntil: 'networkidle0', timeout: 60000 });
await settle();
await page.screenshot({ path: `${out}-list.png` });

// Open a folder from the tree, as a user would.
const clickText = async text => {
  const handle = await page.evaluateHandle(wanted => {
    const matches = [...document.querySelectorAll('body *')].filter(
      element =>
        element.children.length === 0 && element.textContent?.trim() === wanted
    );
    return matches[0] ?? null;
  }, text);
  const element = handle.asElement();
  if (element === null) return false;
  await element.click();
  return true;
};

const opened = await clickText('images');
await settle();
await page.screenshot({ path: `${out}-folder.png` });

// Upload a file into the opened folder through the uploader input.
const input = await page.$('input[type=file]');
let uploaded = false;
if (input !== null && process.env.UPLOAD_FILE) {
  await input.uploadFile(process.env.UPLOAD_FILE);
  uploaded = true;
  await settle();
  await page.screenshot({ path: `${out}-upload.png` });
}

fs.writeFileSync(
  `${out}.json`,
  JSON.stringify({ opened, uploaded, consoleErrors, failed, log }, null, 2)
);
await browser.close();
