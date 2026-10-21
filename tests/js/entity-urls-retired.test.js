/*
 * Unit tests for VoteGA.entityUrls.isRetired() (assets/scripts/entity-urls.js).
 *
 * Search hides a candidate whose page is retired (not on the race's current ballot), but
 * the search index must keep the record because the page builders read it back. So the
 * hiding is a client-side filter keyed on the "retired" map build_entity_pages.py writes
 * into entity-urls.json.
 *
 * Run: node --test tests/js/*.test.js
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { loadBrowserModules } = require('./load-browser-module');

const { VoteGA } = loadBrowserModules('assets/scripts/entity-urls.js');
const { isRetired } = VoteGA.entityUrls;

const maps = { retired: { candidate: { 'ga-house-1-2026-r-2': true } }, candidate: {} };
const cand = (id) => ({ category: 'Candidate', url: `candidate.html?id=${id}` });

test('a retired candidate is hidden', () => {
  assert.strictEqual(isRetired(cand('ga-house-1-2026-r-2'), maps), true);
});

test('a live candidate is not hidden', () => {
  assert.strictEqual(isRetired(cand('ga-house-1-2026-d-1'), maps), false);
});

test('a missing or empty map hides nothing (the map is a build artifact that can be absent)', () => {
  assert.strictEqual(isRetired(cand('ga-house-1-2026-r-2'), {}), false);
  assert.strictEqual(isRetired(cand('ga-house-1-2026-r-2'), null), false);
  assert.strictEqual(isRetired(cand('ga-house-1-2026-r-2'), { retired: {} }), false);
});

test('only candidates are ever retired, even if an id collides with another category', () => {
  assert.strictEqual(isRetired({ category: 'Race', url: 'race.html?id=ga-house-1-2026-r-2' }, maps), false);
  assert.strictEqual(isRetired({ category: 'Local Government', url: 'local/x/' }, maps), false);
});

test('a record with no id in its url is not hidden', () => {
  assert.strictEqual(isRetired({ category: 'Candidate', url: 'candidate.html' }, maps), false);
  assert.strictEqual(isRetired(null, maps), false);
});
