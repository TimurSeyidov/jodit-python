// Reference WHATWG URL parsing (new URL(url).pathname) for
// tests/unit/test_resolve_url.py.
//
//   node scripts/generate_url_fixtures.cjs > tests/fixtures/url_cases.json
const urls = [
  'http://localhost:8081/files/test/a.txt', 'http://x', 'http://x/',
  'https://x/a/b/../c', 'http://x/a/./b/.', 'http://x/a/%2e%2e/b',
  'http://x/a/b/..', 'http://x/../../etc/passwd', 'http:x/y', 'http:/x/y',
  'http://x\\a\\b', 'http://x/a?q=1#h', 'http://x/a#h?q', 'http://',
  'http://:80/', 'http://x:99999/', 'http://x:abc/', 'http://x:/a',
  'http://user:pass@host:8080/p', 'http://[::1]/p', 'http://[::1]:81/p',
  'mailto:user@example.com', 'data:text/plain,hi', 'file:///etc/passwd',
  'file:/a/../b', 'file://host/share/x', 'nope', '', '/relative/path',
  '1http://x/', '  http://x/trim  ', 'http://x/a b/ç', 'ftp://h/f',
  'ws://h:1/s', 'HTTP://X/Up', 'http://x/%2E/y', 'http://x/.%2e/y',
];
const cases = urls.map(url => {
  try {
    return { url, pathname: new URL(url).pathname };
  } catch {
    return { url, pathname: null };
  }
});
process.stdout.write(JSON.stringify(cases, null, 1) + '\n');
