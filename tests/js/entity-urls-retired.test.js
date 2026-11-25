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

// --- search results: former members are findable, labelled, and last (D8) ---
const { searchRecords, isFormer } = VoteGA.entityUrls;
const searchMaps = {
  retired: { candidate: { c1: true }, 'ga-legislator': { m1: true, m2: true } },
  'ga-legislator': { m1: '/ga-legislators/old-one/', m2: '/ga-legislators/old-two/', m3: '/ga-legislators/now/' },
  'us-congress-former': { F1: '/us-congress/old-fed/' },
};
const leg = (id, former) => ({ title: id, desc: '', category: 'GA Legislator', url: `ga-member.html?id=${id}`, former });
const fed = (id, former) => ({ title: id, desc: '', category: 'U.S. Congress', url: `member.html?bioguideId=${id}`, former });
// Objects cross the module's vm realm, so compare as JSON.
const plain = (x) => JSON.parse(JSON.stringify(x));

test('former members are labelled, resolved and listed after everyone current', () => {
  const out = plain(searchRecords([leg('m1', 'current'), fed('F1', '119th'), leg('m3')], searchMaps, ''));
  assert.deepStrictEqual(out.map((r) => [r.title, r.category, r.url]), [
    ['m3', 'GA Legislator', '/ga-legislators/now/'],
    ['m1', 'Former GA Legislator', '/ga-legislators/old-one/'],
    ['F1', 'Former Member of Congress', '/us-congress/old-fed/'],
  ]);
});

test('a member who left since the index was built is labelled from the maps', () => {
  assert.strictEqual(isFormer(leg('m2'), searchMaps), true);
  assert.strictEqual(isFormer(fed('F1'), searchMaps), true);
});

test('the index label alone is enough when the maps are missing', () => {
  assert.deepStrictEqual(plain(searchRecords([leg('m1', 'current')], {}, '')).map((r) => r.category),
    ['Former GA Legislator']);
});

test('off-ballot candidates stay hidden', () => {
  assert.strictEqual(searchRecords([cand('c1'), cand('c2')], searchMaps, '').length, 1);
});
