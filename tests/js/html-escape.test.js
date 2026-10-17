/*
 * Unit tests for VoteGA.escapeHtml() and VoteGA.safeUrl()
 * (assets/scripts/html-escape.js).
 *
 * Run: node --test tests/js/*.test.js
 *
 * safeUrl() exists because escaping alone is not enough for a link. The
 * federal-executive page builds its executive-order and agency-rule lists from
 * the Federal Register API and its laws list from the generated Congress.gov
 * feed, dropping each document's title, abstract and html_url straight into
 * innerHTML. A quote in a title closed the attribute it sat in; a
 * javascript: URL in an href contains nothing an escaper would touch. These
 * pin both halves.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { loadBrowserModules } = require('./load-browser-module');

const { VoteGA } = loadBrowserModules('assets/scripts/html-escape.js');
const { escapeHtml, safeUrl } = VoteGA;

test('escapeHtml neutralises every character that can break out of markup', () => {
  assert.strictEqual(
    escapeHtml('<img src=x onerror="alert(1)">'),
    '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;'
  );
  assert.strictEqual(escapeHtml("O'Brien & Sons"), 'O&#39;Brien &amp; Sons');
});

test('escapeHtml renders a missing value as empty, not "undefined"', () => {
  assert.strictEqual(escapeHtml(null), '');
  assert.strictEqual(escapeHtml(undefined), '');
  assert.strictEqual(escapeHtml(0), '0');
});

test('safeUrl keeps the link shapes the site actually uses', () => {
  assert.strictEqual(
    safeUrl('https://www.federalregister.gov/documents/2026/01/02/2026-00001/x'),
    'https://www.federalregister.gov/documents/2026/01/02/2026-00001/x'
  );
  assert.strictEqual(safeUrl('http://example.gov/a'), 'http://example.gov/a');
  assert.strictEqual(safeUrl('/federal-executives/donald-j-trump/'), '/federal-executives/donald-j-trump/');
  assert.strictEqual(safeUrl('#campaignFinance'), '#campaignFinance');
});

test('safeUrl escapes an allowed URL so it cannot leave its attribute', () => {
  assert.strictEqual(
    safeUrl('https://example.gov/a?x=1&y=2"><script>alert(1)</script>'),
    'https://example.gov/a?x=1&amp;y=2&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;'
  );
});

test('safeUrl rejects a scheme the browser would execute', () => {
  assert.strictEqual(safeUrl('javascript:alert(1)'), '#');
  assert.strictEqual(safeUrl('JaVaScRiPt:alert(1)'), '#');
  // Leading whitespace is stripped before the check, so padding does not slip past.
  assert.strictEqual(safeUrl('  javascript:alert(1)'), '#');
  assert.strictEqual(safeUrl('data:text/html,<script>alert(1)</script>'), '#');
  assert.strictEqual(safeUrl('vbscript:msgbox(1)'), '#');
});

test('safeUrl returns a harmless target for a missing URL', () => {
  assert.strictEqual(safeUrl(null), '#');
  assert.strictEqual(safeUrl(undefined), '#');
  assert.strictEqual(safeUrl(''), '#');
});
